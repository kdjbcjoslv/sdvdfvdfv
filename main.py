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
            if r.status_code != 200:
                print(f"    ❌ Error API Telegram (Video): Código {r.status_code} - {r.text}")
            return r.status_code == 200
    except Exception as e:
        print(f"    ❌ Error de conexión (Video): {e}")
        return False

def enviar_foto_telegram(photo_path, caption):
    """Envía una foto a Telegram con soporte para HTML."""
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as photo:
            payload = {'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}
            files = {'photo': photo}
            r = requests.post(url, data=payload, files=files)
            if r.status_code != 200:
                print(f"    ❌ Error API Telegram (Foto): Código {r.status_code} - {r.text}")
            return r.status_code == 200
    except Exception as e:
        print(f"    ❌ Error de conexión (Foto): {e}")
        return False

# --- INICIO DEL PROCESO ---

print("--- 🛠️ INICIO DEL DEBUG ---")
if not TOKEN: print("⚠️ Alerta: TOKEN no configurado.")
if not CHAT_ID: print("⚠️ Alerta: CHAT_ID no configurado.")

if not USUARIOS:
    print("❌ Error: Lista de usuarios vacía o no detectada.")
    exit()

print(f"🚀 Bot despertando... Analizando {len(USUARIOS)} cuentas en total.")

if not os.path.exists("temp_media"):
    os.makedirs("temp_media")
    print("📁 Carpeta temporal creada.")

for i, user in enumerate(USUARIOS, 1):
    print(f"\n👤 [Usuario #{i}] Iniciando descarga...")
    tiktok_user = user if user.startswith('@') else f'@{user}'
    
    # Ejecución de yt-dlp con captura de errores
    resultado_dl = subprocess.run([
        'yt-dlp',
        '--quiet', '--no-warnings',
        '--download-archive', 'archive.txt',
        '--dateafter', 'now-4day',
        '--playlist-end', '20',
        '--impersonate', 'chrome',
        '-o', 'temp_media/%(uploader)s_%(id)s.%(ext)s', 
        f'https://www.tiktok.com/{tiktok_user}'
    ], capture_output=True, text=True)

    if resultado_dl.returncode != 0:
        print(f"  ⚠️ Error en yt-dlp para Usuario #{i}. Saltando a revisión de archivos...")
        # No hacemos exit() para que siga con el siguiente usuario
    else:
        print(f"  📥 Descarga completada para Usuario #{i}.")

    # 3. Procesar archivos descargados
    archivos = glob.glob("temp_media/*")
    if not archivos:
        print(f"  Empty: No hay archivos nuevos para el Usuario #{i}.")
    
    for j, file_path in enumerate(archivos, 1):
        ext = os.path.splitext(file_path)[1].lower()
        # Mantenemos el caption original con el link real, pero el log de consola será anónimo
        caption = f'🎬 Nuevo de: <a href="https://www.tiktok.com/{tiktok_user}">{user}</a>'
        
        print(f"  📦 Procesando Archivo #{j} de Usuario #{i} (Ext: {ext})...", end=" ")
        
        exito = False
        if ext in ['.mp4', '.webm', '.mov']:
            exito = enviar_video_telegram(file_path, caption)
        elif ext in ['.jpg', '.jpeg', '.png', '.webp']:
            exito = enviar_foto_telegram(file_path, caption)
        
        if exito:
            os.remove(file_path)
            print("✅ OK")
        else:
            print("❌ FALLÓ")

print("\n--- ✨ Proceso finalizado ---")
