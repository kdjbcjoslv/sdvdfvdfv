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
    path = shutil.which("ffmpeg")
    if path:
        logger(f"✅ Motor de vídeo detectado.")
        return True
    logger("❌ ERROR: FFmpeg no encontrado en el sistema.")
    return False

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
    logger(f"   📸 Post {video_id} es un carrusel. Iniciando montaje...")
    
    # 1. Intentar bajar imágenes
    subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings', '--skip-download',
        '--write-all-thumbnails', '--impersonate', 'chrome',
        '-o', f'temp_media/{video_id}',
        f'https://www.tiktok.com/video/{video_id}'
    ], capture_output=True)

    fotos = sorted(glob.glob(f"temp_media/{video_id}*"))
    fotos = [f for f in fotos if f.lower().endswith(('.jpg', '.jpeg', '.webp', '.png'))]

    if not fotos:
        logger(f"   ❌ Fallo al obtener imágenes del carrusel {video_id}")
        return None

    logger(f"   🖼️ {len(fotos)} imágenes listas. Renderizando...")
    output_video = f"temp_media/{video_id}_final.mp4"
    
    try:
        # Unión de fotos y audio (2.5 segundos por foto)
        # El filtro scale asegura que el vídeo sea compatible con Telegram (dimensiones pares)
        ffmpeg_cmd = [
            'ffmpeg', '-y', '-v', 'error',
            '-framerate', '1/2.5',
            '-pattern_type', 'glob', '-i', f'temp_media/{video_id}*.[jwp][pe][ngb]*',
            '-i', audio_path,
            '-c:v', 'libx264', '-r', '30', '-pix_fmt', 'yuv420p',
            '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
            '-shortest', output_video
        ]
        subprocess.run(ffmpeg_cmd, check=True)
        return output_video
    except Exception as e:
        logger(f"   ❌ Error FFmpeg en el renderizado: {e}")
        return None

def procesar_descarga(url_tiktok):
    logger("🚀 Escaneando actividad...")
    subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--dateafter', 'now-2day', '--playlist-end', '5',
        '--impersonate', 'chrome',
        '-f', 'bestvideo+bestaudio/best', '--merge-output-format', 'mp4',
        '-o', 'temp_media/%(id)s.%(ext)s',
        url_tiktok
    ], capture_output=True)

# --- EJECUCIÓN ---
verificar_ffmpeg()
limpiar_temp()
archive_ids = cargar_archive()

for i, user in enumerate(USUARIOS, 1):
    logger(f"\n👤 [Cuenta #{i}/{len(USUARIOS)}] Iniciando...")
    tiktok_user = user if user.startswith('@') else f'@{user}'
    user_hashtag = re.sub(r'[^a-zA-Z0-9_]', '_', user.lstrip('@'))
    caption_tg = f'🎬 Nuevo de: <a href="https://www.tiktok.com/{tiktok_user}">{user}</a>\n\n#{user_hashtag}'
    
    procesar_descarga(f'https://www.tiktok.com/{tiktok_user}')

    ficheros = glob.glob("temp_media/*")
    # Agrupamos por ID para saber qué tenemos de cada post
    ids_en_temp = set(os.path.basename(f).split('.')[0].split('_')[0] for f in ficheros)

    enviados_cuenta = 0
    for vid_id in ids_en_temp:
        if vid_id in archive_ids:
            for f in glob.glob(f"temp_media/{vid_id}*"): os.remove(f)
            continue

        video_final = None
        path_mp4 = f"temp_media/{vid_id}.mp4"
        path_m4a = f"temp_media/{vid_id}.m4a"

        # Prioridad 1: Vídeo real
        if os.path.exists(path_mp4):
            video_final = path_mp4
        # Prioridad 2: Carrusel (Audio solo)
        elif os.path.exists(path_m4a):
            video_final = crear_slideshow(vid_id, path_m4a)

        if video_final and os.path.exists(video_final):
            logger(f"   📦 Enviando fichero ({os.path.getsize(video_final)//1024} KB)...")
            if enviar_video(video_final, caption_tg):
                guardar_en_archive(vid_id)
                enviados_cuenta += 1
                logger(f"   ✅ Post {vid_id} enviado.")
            
        # Limpieza por cada post procesado
        for f in glob.glob(f"temp_media/{vid_id}*"):
            try: os.remove(f)
            except: pass

    logger(f"📊 Resumen: {enviados_cuenta} nuevos.")

logger("\n--- ✨ Proceso completado ---")
