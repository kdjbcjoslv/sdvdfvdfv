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

def verificar_sistema():
    logger("--- 🛠️ VERIFICACIÓN DE SISTEMA ---")
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        logger(f"✅ FFmpeg detectado en: {ffmpeg_path}")
    else:
        logger("❌ ERROR: FFmpeg NO detectado. Los carruseles NO se convertirán en vídeo sin esto.")
    
    if not TOKEN or not CHAT_ID:
        logger("⚠️ Faltan variables de entorno de Telegram.")

def cargar_archive():
    if not os.path.exists(ARCHIVE):
        return set()
    with open(ARCHIVE, "r") as f:
        return {line.strip().split()[-1] for line in f if line.strip()}

def guardar_en_archive(video_id):
    with open(ARCHIVE, "a") as f:
        f.write(f"tiktok {video_id}\n")

def limpiar_temp():
    if not os.path.exists("temp_media"):
        os.makedirs("temp_media")
    for f in glob.glob("temp_media/*"):
        try: os.remove(f)
        except: pass

def enviar_video(path, caption):
    url = f"https://api.telegram.org/bot{TOKEN}/sendVideo"
    try:
        with open(path, 'rb') as f:
            r = requests.post(
                url, 
                data={'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}, 
                files={'video': f}
            )
            return r.status_code == 200
    except:
        return False

def descargar_con_debug(url_tiktok):
    logger(f"🚀 Iniciando yt-dlp para una cuenta...")
    
    # Ejecutamos y capturamos TODO el texto de yt-dlp
    resultado = subprocess.run([
        'yt-dlp',
        '--no-warnings',
        '--dateafter', 'now-2day',
        '--playlist-end', '2', # Reducido a 2 para el debug rápido
        '--impersonate', 'chrome',
        '-f', 'best', 
        '--merge-output-format', 'mp4',
        '-o', 'temp_media/%(id)s.%(ext)s',
        url_tiktok
    ], capture_output=True, text=True)

    # Imprimimos lo que yt-dlp ha hecho internamente (limpiando URLs por privacidad)
    if resultado.stdout:
        # Filtramos URLs para mantener privacidad en el log
        clean_stdout = re.sub(r'https?://\S+', '[URL_OCULTA]', resultado.stdout)
        print(f"\n--- DEBUG YT-DLP (SALIDA) ---\n{clean_stdout}\n---------------------------\n")
    
    if resultado.stderr:
        clean_stderr = re.sub(r'https?://\S+', '[URL_OCULTA]', resultado.stderr)
        print(f"\n--- DEBUG YT-DLP (ERRORES) ---\n{clean_stderr}\n---------------------------\n")

# --- PROCESO PRINCIPAL ---
verificar_sistema()
limpiar_temp()

for i, user in enumerate(USUARIOS, 1):
    logger(f"\n👤 PROCESANDO CUENTA #{i} (Total: {len(USUARIOS)})")
    
    tiktok_user = user if user.startswith('@') else f'@{user}'
    user_hashtag = re.sub(r'[^a-zA-Z0-9_]', '_', user.lstrip('@'))
    caption_tg = f'🎬 Nuevo de: <a href="https://www.tiktok.com/{tiktok_user}">{user}</a>\n\n#{user_hashtag}'
    
    archive_ids = cargar_archive()
    descargar_con_debug(f'https://www.tiktok.com/{tiktok_user}')

    # --- INSPECCIÓN DE ARCHIVOS ---
    archivos_encontrados = glob.glob("temp_media/*")
    logger(f"📂 Archivos en carpeta temporal: {len(archivos_encontrados)}")
    
    for f in archivos_encontrados:
        nombre = os.path.basename(f)
        peso = os.path.getsize(f) / (1024 * 1024) # MB
        logger(f"   -> Fichero: {nombre} | Ext: {os.path.splitext(f)[1]} | Tamaño: {peso:.2f} MB")

    # --- LÓGICA DE TRATAMIENTO ---
    nuevos = 0
    for video_path in archivos_encontrados:
        if not video_path.lower().endswith(VIDEO_EXTS):
            logger(f"   ⚠️ Ignorando {os.path.basename(video_path)}: No es un formato de vídeo soportado.")
            continue
            
        vid_id = os.path.basename(video_path).split('.')[0]
        
        if vid_id in archive_ids:
            logger(f"   ⏭️ Saltando {vid_id}: Ya está en el archivo.")
            os.remove(video_path)
            continue

        logger(f"   📤 Intentando enviar a Telegram: {vid_id}...")
        if enviar_video(video_path, caption_tg):
            guardar_en_archive(vid_id)
            logger(f"   ✅ {vid_id} enviado con éxito.")
            nuevos += 1
            os.remove(video_path)
        else:
            logger(f"   ❌ Error al enviar {vid_id} a la API de Telegram.")

    logger(f"📊 Resumen cuenta #{i}: {nuevos} enviados.")

logger("\n--- ✨ FIN DEL DIAGNÓSTICO ---")
