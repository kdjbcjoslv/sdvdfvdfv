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
    print(mensaje, flush=True, **kwargs)

def limpiar_hashtag(nombre):
    nombre = nombre.lstrip('@')
    tag = re.sub(r'[^a-zA-Z0-9_]', '_', nombre)
    return re.sub(r'_+', '_', tag).strip('_')

def eliminar_id_de_archivo(video_id):
    if not os.path.exists("archive.txt"): return
    try:
        with open("archive.txt", "r") as f:
            lineas = f.readlines()
        with open("archive.txt", "w") as f:
            for linea in lineas:
                if video_id not in linea:
                    f.write(linea)
        logger(f"    ♻️ Historial reseteado para {video_id}")
    except Exception: pass

# --- SISTEMA DE ENVÍO POR LOTES ---
def enviar_carrusel_completo(archivos_fotos, caption):
    """Manda todas las fotos en grupos de 10 (límite de Telegram)."""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMediaGroup"
    exito_total = True
    
    # Ordenar alfabéticamente para que el carrusel mantenga el orden original (01, 02, 03...)
    archivos_fotos.sort()

    for i in range(0, len(archivos_fotos), 10):
        lote = archivos_fotos[i : i + 10]
        n_lote = (i // 10) + 1
        
        media = []
        files = {}
        
        for j, path in enumerate(lote):
            file_key = f"f{j}"
            # Caption solo en la primera foto del primer lote
            txt = ""
            if i == 0 and j == 0:
                txt = caption
            elif j == 0:
                txt = f"Continuación ({n_lote})"
            
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
                logger(f"    ❌ Error lote {n_lote}: {r.text}")
            
            for f in files.values(): f.close()
            time.sleep(3) # Un poco más de margen para carruseles grandes
        except Exception as e:
            exito_total = False
            logger(f"    ❌ Error envío: {e}")
            for f in files.values(): f.close()

    return exito_total

def enviar_single(tipo, path, caption):
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
    logger(f"\n👤 [Usuario #{i}] Revisando {user}...")
    tiktok_user = user if user.startswith('@') else f'@{user}'
    user_hashtag = limpiar_hashtag(user)
    caption_tg = f'🎬 Nuevo de: <a href="https://www.tiktok.com/{tiktok_user}">{user}</a>\n\n#{user_hashtag}'

    # DESCARGA: Usamos un template que previene problemas con carruseles
    # %(id)s_%(playlist_index)s asegura que las fotos del carrusel tengan el mismo ID base
    subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--download-archive', 'archive.txt',
        '--dateafter', 'now-4day',
        '--playlist-end', '20', # Revisar los 5 más recientes es suficiente
        '--impersonate', 'chrome',
        '-o', 'temp_media/%(id)s_%(playlist_index)02d.%(ext)s', 
        f'https://www.tiktok.com/{tiktok_user}'
    ])

    # AGRUPACIÓN INTELIGENTE
    archivos_en_carpeta = glob.glob("temp_media/*")
    
    # Extraemos solo el ID de TikTok (los primeros 19 dígitos aprox)
    # Si el archivo es "7341234567890123456_01.jpg", el ID es "7341234567890123456"
    ids_en_carpeta = set()
    for f in archivos_en_carpeta:
        nombre = os.path.basename(f)
        match = re.match(r'^(\d+)', nombre)
        if match:
            ids_en_carpeta.add(match.group(1))

    for vid_id in ids_en_carpeta:
        # Buscamos todos los archivos que empiecen por ese ID exacto
        post_files = sorted(glob.glob(f"temp_media/{vid_id}*"))
        
        fotos = [f for f in post_files if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
        videos = [f for f in post_files if f.lower().endswith(('.mp4', '.webm', '.mov'))]

        # Prioridad: Si hay fotos, es un carrusel (aunque yt-dlp a veces baje el audio como video)
        exito = False
        if fotos:
            if len(fotos) > 1:
                logger(f"    🖼️ Enviando carrusel ({len(fotos)} fotos)...")
                exito = enviar_carrusel_completo(fotos, caption_tg)
            else:
                logger(f"    📷 Enviando foto suelta...")
                exito = enviar_single("photo", fotos[0], caption_tg)
        elif videos:
            logger(f"    📦 Enviando vídeo...")
            exito = enviar_single("video", videos[0], caption_tg)

        if exito:
            logger("    ✅ OK")
            for f in post_files: 
                if os.path.exists(f): os.remove(f)
        else:
            logger("    ❌ FALLÓ envío")
            eliminar_id_de_archivo(vid_id)
            for f in post_files:
                if os.path.exists(f): os.remove(f)

# Limpieza de archivos basura (como archivos de audio/m4a que yt-dlp descarga a veces)
for f in glob.glob("temp_media/*"):
    try: os.remove(f)
    except: pass

logger("\n--- ✨ Fin del proceso ---")
