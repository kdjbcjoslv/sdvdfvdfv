import os
import subprocess
import requests
import glob
import sys
import time
import re
import json

# --- CONFIGURACIÓN ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
USUARIOS_RAW = os.getenv("LISTA_USUARIOS", "")
USUARIOS = [u.strip() for u in USUARIOS_RAW.replace('\n', ',').split(",") if u.strip()]

def logger(mensaje, **kwargs):
    """Logs anónimos para GitHub Actions."""
    print(mensaje, flush=True, **kwargs)

def limpiar_hashtag(nombre):
    """Crea un hashtag válido sin puntos ni caracteres raros."""
    nombre = nombre.lstrip('@')
    tag = re.sub(r'[^a-zA-Z0-9_]', '_', nombre)
    return re.sub(r'_+', '_', tag).strip('_')

def eliminar_id_de_archivo(video_id):
    """Limpia el ID del historial para permitir reintentos."""
    if not os.path.exists("archive.txt"): return
    try:
        with open("archive.txt", "r") as f:
            lineas = f.readlines()
        with open("archive.txt", "w") as f:
            for linea in lineas:
                if video_id not in linea:
                    f.write(linea)
        logger("    ♻️ Historial reseteado para este post.")
    except Exception: pass

# --- NUEVA FUNCIÓN DE ENVÍO POR LOTES ---
def enviar_carrusel_completo(archivos_fotos, caption):
    """Divide las fotos en grupos de 10 y las envía todas."""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMediaGroup"
    exito_total = True
    
    # Dividimos la lista de fotos en trozos de 10
    # Ejemplo: Si hay 25 fotos, hará 3 envíos (10, 10 y 5)
    for i in range(0, len(archivos_fotos), 10):
        lote = archivos_fotos[i : i + 10]
        n_lote = (i // 10) + 1
        
        media = []
        files = {}
        
        for j, path in enumerate(lote):
            file_key = f"f{j}"
            # Solo ponemos el caption en la primera foto del primer lote
            txt = f"{caption} (Parte {n_lote})" if i > 0 and j == 0 else (caption if i == 0 and j == 0 else "")
            
            media.append({
                'type': 'photo',
                'media': f'attach://{file_key}',
                'caption': txt,
                'parse_mode': 'HTML'
            })
            files[file_key] = open(path, 'rb')

        try:
            r = requests.post(url, data={'chat_id': CHAT_ID, 'media': json.dumps(media)}, files=files)
            if r.status_code != 200:
                exito_total = False
                logger(f"    ❌ Error en lote {n_lote}: {r.status_code}")
            
            # Cerrar archivos y esperar un poco para no saturar
            for f in files.values(): f.close()
            time.sleep(2) 
        except Exception:
            exito_total = False
            for f in files.values(): f.close()

    return exito_total

def enviar_single(tipo, path, caption):
    """Envía un archivo individual (vídeo o foto suelta)."""
    metodo = "sendVideo" if tipo == "video" else "sendPhoto"
    url = f"https://api.telegram.org/bot{TOKEN}/{metodo}"
    try:
        with open(path, 'rb') as f:
            r = requests.post(url, data={'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}, files={tipo: f})
            return r.status_code == 200
    except Exception: return False

# --- PROCESO ---

logger(f"--- 🛠️ INICIANDO SCAN ({len(USUARIOS)} cuentas) ---")

if not os.path.exists("temp_media"): os.makedirs("temp_media")

for i, user in enumerate(USUARIOS, 1):
    logger(f"\n👤 [Usuario #{i}] Revisando...")
    tiktok_user = user if user.startswith('@') else f'@{user}'
    user_hashtag = limpiar_hashtag(user)
    
    # Caption que solo se verá en Telegram
    caption_tg = f'🎬 Nuevo de: <a href="https://www.tiktok.com/{tiktok_user}">{user}</a>\n\n#{user_hashtag}'

    subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--download-archive', 'archive.txt',
        '--dateafter', 'now-4day',
        '--playlist-end', '10',
        '--impersonate', 'chrome',
        '-o', 'temp_media/%(id)s.%(ext)s', 
        f'https://www.tiktok.com/{tiktok_user}'
    ])

    # Agrupar por ID para no separar carruseles
    archivos_actuales = glob.glob("temp_media/*")
    ids_en_carpeta = set(os.path.basename(f).split('.')[0] for f in archivos_actuales)

    for vid_id in ids_en_carpeta:
        post_files = sorted(glob.glob(f"temp_media/{vid_id}.*"))
        
        fotos = [f for f in post_files if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
        videos = [f for f in post_files if f.lower().endswith(('.mp4', '.webm', '.mov'))]

        exito = False
        if videos:
            logger(f"  📦 Enviando vídeo...")
            exito = enviar_single("video", videos[0], caption_tg)
        elif fotos:
            if len(fotos) > 1:
                logger(f"  🖼️ Enviando carrusel completo ({len(fotos)} fotos)...")
                exito = enviar_carrusel_completo(fotos, caption_tg)
            else:
                logger(f"  📷 Enviando foto suelta...")
                exito = enviar_single("photo", fotos[0], caption_tg)
        
        if exito:
            logger("  ✅ OK")
            for f in post_files: 
                if os.path.exists(f): os.remove(f)
        else:
            logger("  ❌ FALLÓ")
            eliminar_id_de_archivo(vid_id)
            for f in post_files:
                if os.path.exists(f): os.remove(f)

logger("\n--- ✨ Fin del proceso ---")
