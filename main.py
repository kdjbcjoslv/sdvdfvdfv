import os
import subprocess
import requests
import glob

# --- CONFIGURACIÓN Y CARGA DE SECRETOS ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
USUARIOS_RAW = os.getenv("LISTA_USUARIOS", "")

USUARIOS = [u.strip() for u in USUARIOS_RAW.replace('\n', ',').split(",") if u.strip()]

def enviar_video_telegram(video_path, caption):
    """Envía un vídeo a Telegram con soporte para HTML."""
    url = f"https://api.telegram.org/bot{TOKEN}/sendVideo"
    try:
        with open(video_path, 'rb') as video:
            payload = {'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}
            files = {'video': video}
            r = requests.post(url, data=payload, files=files)
            return r.status_code == 200
    except Exception:
        return False

def enviar_foto_telegram(photo_path, caption):
    """Envía una foto a Telegram con soporte para HTML."""
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as photo:
            payload = {'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}
            files = {'photo': photo}
            r = requests.post(url, data=payload, files=files)
            return r.status_code == 200
    except Exception:
        return False

# --- INICIO DEL PROCESO ---

if not USUARIOS:
    print("❌ Error: Lista de usuarios no detectada.")
    exit()

print(f"🚀 Bot despertando... Revisando {len(USUARIOS)} cuentas.")

if not os.path.exists("temp_media"):
    os.makedirs("temp_media")

for i, user in enumerate(USUARIOS, 1):
    tiktok_user = user if user.startswith('@') else f'@{user}'
    
    # yt-dlp descargará vídeos (.mp4) y fotos (.jpg/.png)
    subprocess.run([
        'yt-dlp',
        '--quiet', '--no-warnings',
        '--download-archive', 'archive.txt',
        '--dateafter', 'now-4day',
        '--playlist-end', '20',
        '--impersonate', 'chrome',
        '-o', 'temp_media/%(uploader)s_%(id)s.%(ext)s', 
        f'https://www.tiktok.com/{tiktok_user}'
    ])

    # 3. Procesar TODOS los archivos descargados
    archivos = glob.glob("temp_media/*")
    for file_path in archivos:
        ext = os.path.splitext(file_path)[1].lower()
        # Creamos el nombre con enlace clicable
        caption = f'🎬 Nuevo de: <a href="https://www.tiktok.com/{tiktok_user}">{user}</a>'
        
        if ext in ['.mp4', '.webm', '.mov']:
            exito = enviar_video_telegram(file_path, caption)
        elif ext in ['.jpg', '.jpeg', '.png', '.webp']:
            exito = enviar_foto_telegram(file_path, caption)
        else:
            continue # Ignorar otros formatos

        if exito:
            os.remove(file_path)
            print(f"✅ Enviado: {os.path.basename(file_path)}")

print("✨ Proceso finalizado.")
