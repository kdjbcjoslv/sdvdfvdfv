import os
import subprocess
import requests
import glob

# --- CONFIGURACIÓN Y CARGA DE SECRETOS ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
USUARIOS_RAW = os.getenv("LISTA_USUARIOS", "")

# Limpieza de lista: acepta comas o saltos de línea
USUARIOS = [u.strip() for u in USUARIOS_RAW.replace('\n', ',').split(",") if u.strip()]

def enviar_video_telegram(video_path, caption):
    """Envía un archivo de vídeo a Telegram."""
    url = f"https://api.telegram.org/bot{TOKEN}/sendVideo"
    try:
        with open(video_path, 'rb') as video:
            payload = {'chat_id': CHAT_ID, 'caption': caption}
            files = {'video': video}
            r = requests.post(url, data=payload, files=files)
            return r.status_code == 200
    except Exception:
        return False

# --- INICIO DEL PROCESO ---

if not USUARIOS:
    print("❌ Error: Lista de usuarios no detectada en el Secret.")
    exit()

# 1. Mensaje de inicio (Antes de todo)
print(f"🚀 Bot despertando... Detectadas {len(USUARIOS)} cuentas.")

if not os.path.exists("temp_videos"):
    os.makedirs("temp_videos")

# 2. Bucle de revisión
for i, user in enumerate(USUARIOS, 1):
    tiktok_user = user if user.startswith('@') else f'@{user}'
    
    # Ejecución de yt-dlp con tus parámetros (4 días / 20 vídeos)
    resultado = subprocess.run([
        'yt-dlp',
        '--quiet',
        '--no-warnings',
        '--download-archive', 'archive.txt',
        '--dateafter', 'now-4day',       
        '--playlist-end', '20',
        '--no-playlist',
        '--impersonate', 'chrome',
        '-o', 'temp_videos/%(uploader)s_%(id)s.%(ext)s', 
        f'https://www.tiktok.com/{tiktok_user}'
    ], capture_output=True, text=True)

    # Si hay un error crítico (como bloqueo IP), lo verás en el log
    if "HTTP Error 500" in resultado.stderr:
        print(f"⚠️ Aviso: TikTok devolvió error 500 en la cuenta {i}. Reintentando en 30 min.")

    # 3. Envío de vídeos detectados
    videos_descargados = glob.glob("temp_videos/*.mp4")
    for video_path in videos_descargados:
        # El nombre del usuario solo va a Telegram (Privado)
        exito = enviar_video_telegram(video_path, f"🎬 Nuevo vídeo de: {user}")
        if exito:
            os.remove(video_path) 
            print("✅ Vídeo procesado y enviado con éxito.")

print("✨ Proceso finalizado correctamente.")
