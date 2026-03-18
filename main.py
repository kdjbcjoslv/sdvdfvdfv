import os
import subprocess
import requests
import glob
import sys
import time

def logger(mensaje):
    print(mensaje, flush=True)

def eliminar_id_de_archivo(video_id, archive_path="archive.txt"):
    """Elimina la línea del ID del video de archive.txt si el envío falló."""
    if not os.path.exists(archive_path):
        return
    
    linea_a_eliminar = f"tiktok {video_id}\n"
    
    with open(archive_path, "r") as f:
        lineas = f.readlines()
    
    with open(archive_path, "w") as f:
        for linea in lineas:
            # Si la línea no es la del video que falló, la mantenemos
            if linea.strip() != linea_a_eliminar.strip():
                f.write(linea)
    logger(f"    ♻️ ID {video_id} eliminado de archive.txt (se reintentará luego).")

def enviar_con_reintento(tipo, path, caption):
    """Envía media con gestión de Rate Limit (Error 429)."""
    metodo = "sendVideo" if tipo == "video" else "sendPhoto"
    url = f"https://api.telegram.org/bot{os.getenv('TELEGRAM_TOKEN')}/{metodo}"
    
    intentos = 0
    while intentos < 2:
        try:
            with open(path, 'rb') as f:
                payload = {'chat_id': os.getenv("TELEGRAM_CHAT_ID"), 'caption': caption, 'parse_mode': 'HTML'}
                files = {tipo: f}
                r = requests.post(url, data=payload, files=files)
                
                if r.status_code == 200:
                    return True
                
                if r.status_code == 429:
                    espera = r.json().get('parameters', {}).get('retry_after', 20)
                    logger(f"    ⚠️ Rate Limit. Esperando {espera}s...")
                    time.sleep(espera + 1)
                    intentos += 1
                    continue 
                
                logger(f"    ❌ Error API: {r.status_code}")
                return False
        except Exception as e:
            logger(f"    ❌ Error de conexión: {e}")
            return False
    return False

# --- INICIO ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
USUARIOS_RAW = os.getenv("LISTA_USUARIOS", "")
USUARIOS = [u.strip() for u in USUARIOS_RAW.replace('\n', ',').split(",") if u.strip()]

logger("--- 🛠️ DEBUG INICIADO (Lógica de Archivo Dinámica) ---")

if not os.path.exists("temp_media"):
    os.makedirs("temp_media")

for i, user in enumerate(USUARIOS, 1):
    logger(f"\n👤 [Usuario #{i}] Analizando...")
    tiktok_user = user if user.startswith('@') else f'@{user}'
    
    # IMPORTANTE: El nombre del archivo contendrá el ID para poder recuperarlo si falla
    # Formato: temp_media/ID_DEL_VIDEO.ext
    subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--download-archive', 'archive.txt',
        '--dateafter', 'now-4day',
        '--playlist-end', '20',
        '--impersonate', 'chrome',
        '-o', 'temp_media/%(id)s.%(ext)s', 
        f'https://www.tiktok.com/{tiktok_user}'
    ])

    archivos = glob.glob("temp_media/*")
    for j, file_path in enumerate(archivos, 1):
        # El ID es el nombre del archivo (quitando la extensión)
        video_id = os.path.splitext(os.path.basename(file_path))[0]
        ext = os.path.splitext(file_path)[1].lower()
        tipo = "video" if ext in ['.mp4', '.webm', '.mov'] else "photo"
        caption = f'🎬 Nuevo de: <a href="https://www.tiktok.com/{tiktok_user}">{user}</a>'

        logger(f"  📦 Archivo #{j} de Usuario #{i}...", end="")
        
        exito = enviar_con_reintento(tipo, file_path, caption)
        
        if exito:
            os.remove(file_path)
            logger(" ✅ OK")
        else:
            # SI FALLA: Borramos el ID del archive.txt para que yt-dlp lo vuelva a ver "nuevo"
            logger(" ❌ FALLÓ")
            eliminar_id_de_archivo(video_id)
            if os.path.exists(file_path):
                os.remove(file_path) # Limpiamos el temporal para no duplicar espacio

logger("\n--- ✨ Proceso terminado ---")
