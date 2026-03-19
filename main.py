import os
import subprocess
import requests
import glob
import time
import re
import shutil

# --- CONFIGURACIÓN ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
USUARIOS_RAW = os.getenv("LISTA_USUARIOS", "")
USUARIOS = [u.strip() for u in USUARIOS_RAW.replace('\n', ',').split(",") if u.strip()]

ARCHIVE = "archive.txt"
VIDEO_EXTS = ('.mp4', '.webm', '.mov', '.mkv')

def logger(mensaje):
    print(f"[LOG] {mensaje}", flush=True)

def verificar_ffmpeg():
    return shutil.which("ffmpeg") is not None

def cargar_archive():
    if not os.path.exists(ARCHIVE): return set()
    with open(ARCHIVE, "r") as f:
        return {line.strip().split()[-1] for line in f if line.strip()}

def guardar_en_archive(video_id):
    with open(ARCHIVE, "a") as f: f.write(f"tiktok {video_id}\n")

def limpiar_temp():
    if not os.path.exists("temp_media"): os.makedirs("temp_media")
    for f in glob.glob("temp_media/*"):
        try: os.remove(f)
        except: pass

def enviar_video(path, caption):
    url = f"https://api.telegram.org/bot{TOKEN}/sendVideo"
    try:
        with open(path, 'rb') as f:
            r = requests.post(url, data={'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}, files={'video': f})
            return r.status_code == 200
    except: return False

def crear_slideshow(video_id, audio_path):
    """
    Descarga las imágenes del post y las une al audio para crear un MP4.
    """
    logger(f"   📸 Post {video_id} detectado como carrusel. Creando slideshow...")
    
    # 1. Descargar todas las imágenes (thumbnails)
    subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings', '--skip-download',
        '--write-all-thumbnails',
        '-o', f'temp_media/{video_id}',
        f'https://www.tiktok.com/t/{video_id}' # URL genérica o ID
    ], capture_output=True)

    fotos = sorted(glob.glob(f"temp_media/{video_id}.*") + glob.glob(f"temp_media/{video_id}_*"))
    fotos = [f for f in fotos if f.lower().endswith(('.jpg', '.jpeg', '.webp', '.png'))]

    if not fotos:
        logger(f"   ❌ No se pudieron obtener imágenes para {video_id}")
        return None

    output_video = f"temp_media/{video_id}_final.mp4"
    
    # 2. Comando FFmpeg para unir fotos y audio
    # Cada foto durará 2.5 segundos.
    # Usamos un filtro complejo para reescalar todas las fotos al mismo tamaño
    try:
        ffmpeg_cmd = [
            'ffmpeg', '-y', '-v', 'quiet',
            '-framerate', '1/2.5', # Tiempo por foto (1 dividido segundos)
            '-pattern_type', 'glob', '-i', f'temp_media/{video_id}*.jpg', 
            '-i', audio_path,
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-shortest',
            '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', # Asegura dimensiones pares para MP4
            output_video
        ]
        # Si las fotos no son .jpg, ajustamos el patrón
        if not glob.glob(f"temp_media/{video_id}*.jpg"):
             ffmpeg_cmd[6] = f'temp_media/{video_id}*.*'

        subprocess.run(ffmpeg_cmd, check=True)
        return output_video
    except Exception as e:
        logger(f"   ❌ Error en FFmpeg: {e}")
        return None

def procesar_descarga(url_tiktok):
    subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--dateafter', 'now-2day', '--playlist-end', '5',
        '--impersonate', 'chrome',
        '-f', 'bestvideo+bestaudio/best', '--merge-output-format', 'mp4',
        '-o', 'temp_media/%(id)s.%(ext)s',
        url_tiktok
    ], capture_output=True)

# --- PROCESO PRINCIPAL ---
if not verificar_ffmpeg():
    logger("❌ CRÍTICO: FFmpeg no está instalado. No podré procesar carruseles.")

limpiar_temp()
archive_ids = cargar_archive()

for i, user in enumerate(USUARIOS, 1):
    logger(f"\n👤 [Cuenta #{i}] Procesando...")
    tiktok_user = user if user.startswith('@') else f'@{user}'
    user_hashtag = re.sub(r'[^a-zA-Z0-9_]', '_', user.lstrip('@'))
    caption_tg = f'🎬 Nuevo de: <a href="https://www.tiktok.com/{tiktok_user}">{user}</a>\n\n#{user_hashtag}'
    
    procesar_descarga(f'https://www.tiktok.com/{tiktok_user}')

    # Analizar qué ha bajado
    ficheros = glob.glob("temp_media/*")
    
    # Agrupar por ID
    ids_en_temp = set(os.path.basename(f).split('.')[0].split('_')[0] for f in ficheros)

    for vid_id in ids_en_temp:
        if vid_id in archive_ids:
            # Borrar basura de IDs viejos
            for f in glob.glob(f"temp_media/{vid_id}*"): os.remove(f)
            continue

        video_final = None
        
        # Caso A: Se bajó el MP4 directamente
        mp4_path = f"temp_media/{vid_id}.mp4"
        if os.path.exists(mp4_path):
            video_final = mp4_path
        
        # Caso B: Solo se bajó audio (Carrusel)
        elif os.path.exists(f"temp_media/{vid_id}.m4a"):
            video_final = crear_slideshow(vid_id, f"temp_media/{vid_id}.m4a")

        if video_final and os.path.exists(video_final):
            logger(f"   📤 Enviando {vid_id}...")
            if enviar_video(video_final, caption_tg):
                guardar_en_archive(vid_id)
                logger(f"   ✅ Éxito")
            
        # Limpiar todo lo relacionado con este ID
        for f in glob.glob(f"temp_media/{vid_id}*"):
            try: os.remove(f)
            except: pass

logger("\n--- ✨ Fin del proceso ---")
