import os
import subprocess
import requests
import glob
import time
import re

# --- CONFIGURACIÓN ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
USUARIOS_RAW = os.getenv("LISTA_USUARIOS", "")
USUARIOS = [u.strip() for u in USUARIOS_RAW.replace('\n', ',').split(",") if u.strip()]

ARCHIVE = "archive.txt"
VIDEO_EXTS = ('.mp4', '.webm', '.mov', '.mkv')

def logger(mensaje, **kwargs):
    # Solo imprimimos mensajes que no contengan datos sensibles
    print(mensaje, flush=True, **kwargs)

def limpiar_hashtag(nombre):
    nombre = nombre.lstrip('@')
    tag = re.sub(r'[^a-zA-Z0-9_]', '_', nombre)
    return re.sub(r'_+', '_', tag).strip('_')

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
        try:
            os.remove(f)
        except:
            pass

# --- SISTEMA DE ENVÍO ---
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

def descargar_oculto(url_tiktok):
    """Descarga sin mostrar nada en consola."""
    subprocess.run([
        'yt-dlp',
        '--quiet', '--no-warnings', '--no-progress',
        '--dateafter', 'now-2day',
        '--playlist-end', '5',
        '--impersonate', 'chrome',
        '-f', 'bestvideo+bestaudio/best', 
        '--merge-output-format', 'mp4',
        '-o', 'temp_media/%(id)s.%(ext)s',
        url_tiktok
    ], capture_output=True) # Redirigimos el output para que no salga en pantalla

# --- PROCESO PRINCIPAL ---
logger(f"--- 🛠️ INICIANDO ESCANEO ({len(USUARIOS)} cuentas configuradas) ---")
limpiar_temp()

for i, user in enumerate(USUARIOS, 1):
    logger(f"👤 [Cuenta #{i}/{len(USUARIOS)}] Procesando...")
    
    tiktok_user = user if user.startswith('@') else f'@{user}'
    user_hashtag = limpiar_hashtag(user)
    # El caption se crea para Telegram, pero NO se imprime en la consola
    caption_tg = f'🎬 Nuevo de: <a href="https://www.tiktok.com/{tiktok_user}">{user}</a>\n\n#{user_hashtag}'
    
    archive_ids = cargar_archive()
    
    # Descarga silenciosa
    descargar_oculto(f'https://www.tiktok.com/{tiktok_user}')

    videos_descargados = [f for f in glob.glob("temp_media/*") if f.lower().endswith(VIDEO_EXTS)]
    
    nuevos_encontrados = 0
    for video_path in videos_descargados:
        vid_id = os.path.basename(video_path).split('.')[0]
        
        if vid_id in archive_ids:
            os.remove(video_path)
            continue

        nuevos_encontrados += 1
        if enviar_video(video_path, caption_tg):
            guardar_en_archive(vid_id)
            os.remove(video_path)
        else:
            logger("  ⚠️ Error en un envío")

    if nuevos_encontrados > 0:
        logger(f"  ✅ {nuevos_encontrados} post(s) enviado(s) correctamente")
    else:
        logger("  ℹ️ Sin contenido nuevo")

logger("\n--- ✨ Proceso finalizado con éxito ---")
