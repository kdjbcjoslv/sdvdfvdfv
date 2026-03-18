import os
import subprocess
import requests
import glob
import sys
import time
import re

# --- CONFIGURACIÓN ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
USUARIOS_RAW = os.getenv("LISTA_USUARIOS", "")
USUARIOS = [u.strip() for u in USUARIOS_RAW.replace('\n', ',').split(",") if u.strip()]

def logger(mensaje, **kwargs):
    print(mensaje, flush=True, **kwargs)

def limpiar_hashtag(nombre):
    nombre = nombre.lstrip('@')
    tag = re.sub(r'[^a-zA-Z0-9_]', '_', nombre)
    return re.sub(r'_+', '_', tag).strip('_')

def eliminar_id_de_archivo(video_id):
    """Elimina el ID base de archive.txt."""
    if not os.path.exists("archive.txt"): return
    try:
        with open("archive.txt", "r") as f:
            lineas = f.readlines()
        with open("archive.txt", "w") as f:
            for linea in lineas:
                # Comprobamos si la línea contiene el ID (los carruseles comparten ID base)
                if video_id not in linea:
                    f.write(linea)
        logger("    ♻️ Historial limpio para reintento.")
    except Exception: pass

# --- FUNCIÓN DE ENVÍO GRUPAL (CARRUSELES) ---
def enviar_album(archivos_fotos, caption):
    """Envía un grupo de fotos como un álbum (Media Group)."""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMediaGroup"
    
    media = []
    files = {}
    
    # Telegram permite máximo 10 fotos por álbum
    for i, path in enumerate(archivos_fotos[:10]):
        file_name = f"f{i}"
        media.append({
            'type': 'photo',
            'media': f'attach://{file_name}',
            'caption': caption if i == 0 else '', # Solo la primera foto lleva el texto
            'parse_mode': 'HTML'
        })
        files[file_name] = open(path, 'rb')

    try:
        r = requests.post(url, data={'chat_id': CHAT_ID, 'media': requests.utils.quote(str(media).replace("'", '"'))}, files=files)
        # Cerramos archivos
        for f in files.values(): f.close()
        return r.status_code == 200
    except Exception:
        for f in files.values(): f.close()
        return False

def enviar_single(tipo, path, caption):
    """Envía un vídeo o foto individual."""
    metodo = "sendVideo" if tipo == "video" else "sendPhoto"
    url = f"https://api.telegram.org/bot{TOKEN}/{metodo}"
    try:
        with open(path, 'rb') as f:
            r = requests.post(url, data={'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}, files={tipo: f})
            return r.status_code == 200
    except Exception: return False

# --- PROCESO PRINCIPAL ---

logger("--- 🛠️ MODO CARRUSEL ACTIVADO (Privacidad Total) ---")

if not os.path.exists("temp_media"): os.makedirs("temp_media")

for i, user in enumerate(USUARIOS, 1):
    logger(f"\n👤 [Usuario #{i}] Analizando...")
    tiktok_user = user if user.startswith('@') else f'@{user}'
    user_hashtag = limpiar_hashtag(user)
    caption = f'🎬 Nuevo de: <a href="https://www.tiktok.com/{tiktok_user}">{user}</a>\n\n#{user_hashtag}'

    # Descarga: Usamos un formato que facilite agrupar carruseles
    subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--download-archive', 'archive.txt',
        '--dateafter', 'now-4day',
        '--playlist-end', '15',
        '--impersonate', 'chrome',
        '-o', 'temp_media/%(id)s.%(ext)s', 
        f'https://www.tiktok.com/{tiktok_user}'
    ])

    # Agrupamos archivos por ID (para detectar carruseles)
    todos_los_archivos = glob.glob("temp_media/*")
    ids_descargados = set(os.path.basename(f).split('.')[0] for f in todos_los_archivos)

    for vid_id in ids_descargados:
        # Buscamos todos los archivos que pertenecen a este post (ID)
        archivos_post = sorted(glob.glob(f"temp_media/{vid_id}.*"))
        
        fotos = [f for f in archivos_post if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
        videos = [f for f in archivos_post if f.lower().endswith(('.mp4', '.webm', '.mov'))]

        exito = False
        if videos:
            logger(f"  📦 Enviando vídeo...")
            exito = enviar_single("video", videos[0], caption)
        elif fotos:
            if len(fotos) > 1:
                logger(f"  🖼️ Enviando carrusel ({len(fotos)} fotos)...")
                exito = enviar_album(fotos, caption)
            else:
                logger(f"  📷 Enviando foto individual...")
                exito = enviar_single("photo", fotos[0], caption)
        
        # Limpieza
        if exito:
            logger("  ✅ OK")
            for f in archivos_post: os.remove(f)
        else:
            logger("  ❌ FALLÓ")
            eliminar_id_de_archivo(vid_id)
            for f in archivos_post: os.remove(f)

logger("\n--- ✨ Proceso terminado ---")
