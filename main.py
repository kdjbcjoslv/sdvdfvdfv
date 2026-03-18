import os
import subprocess
import requests
import glob
import time
import re
import json

# --- CONFIGURACIÓN ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
USUARIOS_RAW = os.getenv("LISTA_USUARIOS", "")
USUARIOS = [u.strip() for u in USUARIOS_RAW.replace('\n', ',').split(",") if u.strip()]

AUDIO_EXTS = ('.m4a', '.mp3', '.aac', '.ogg', '.opus')
FOTO_EXTS  = ('.jpg', '.jpeg', '.png', '.webp')
VIDEO_EXTS = ('.mp4', '.webm', '.mov')
ARCHIVE    = "archive.txt"

def logger(mensaje, **kwargs):
    print(mensaje, flush=True, **kwargs)

def limpiar_hashtag(nombre):
    nombre = nombre.lstrip('@')
    tag = re.sub(r'[^a-zA-Z0-9_]', '_', nombre)
    return re.sub(r'_+', '_', tag).strip('_')

def cargar_archive():
    """Devuelve un set con todos los IDs ya procesados."""
    if not os.path.exists(ARCHIVE):
        return set()
    with open(ARCHIVE, "r") as f:
        ids = set()
        for line in f:
            line = line.strip()
            if line:
                # formato yt-dlp: "youtube ID" o simplemente "ID"
                partes = line.split()
                ids.add(partes[-1])
        return ids

def guardar_en_archive(video_id):
    """Marca un ID como procesado."""
    with open(ARCHIVE, "a") as f:
        f.write(f"tiktok {video_id}\n")

def limpiar_temp():
    for f in glob.glob("temp_media/*"):
        try:
            os.remove(f)
        except Exception:
            pass

# --- SISTEMA DE ENVÍO ---
def enviar_carrusel_completo(archivos_fotos, caption):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMediaGroup"
    exito_total = True
    archivos_fotos.sort()

    for i in range(0, len(archivos_fotos), 10):
        lote = archivos_fotos[i:i + 10]
        media = []
        files = {}

        for j, path in enumerate(lote):
            file_key = f"f{j}"
            txt = caption if (i == 0 and j == 0) else ""
            media.append({
                'type': 'photo',
                'media': f'attach://{file_key}',
                'caption': txt,
                'parse_mode': 'HTML'
            })
            files[file_key] = open(path, 'rb')

        try:
            r = requests.post(
                url,
                data={'chat_id': CHAT_ID, 'media': json.dumps(media)},
                files=files
            )
            if r.status_code != 200:
                logger(f"    ⚠️ Error Telegram carrusel: {r.text}")
                exito_total = False
        except Exception as e:
            logger(f"    ⚠️ Excepción carrusel: {e}")
            exito_total = False
        finally:
            for f in files.values():
                f.close()

        time.sleep(2)
    return exito_total

def enviar_single(tipo, path, caption):
    metodo = "sendVideo" if tipo == "video" else "sendPhoto"
    url = f"https://api.telegram.org/bot{TOKEN}/{metodo}"
    try:
        with open(path, 'rb') as f:
            r = requests.post(
                url,
                data={'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'},
                files={tipo: f}
            )
            return r.status_code == 200
    except Exception:
        return False

def agrupar_archivos_por_id(archivos):
    grupos = {}
    for path in archivos:
        basename = os.path.basename(path)
        match = re.match(r'^([^_]+(?:_[^_]+)*?)(?:_slideshow_\d+|_\d+)?\.', basename)
        vid_id = match.group(1) if match else basename.split('.')[0]
        grupos.setdefault(vid_id, []).append(path)
    return grupos

def descargar(url_tiktok, formato):
    """Descarga sin --download-archive para no bloquear formatos alternativos."""
    subprocess.run([
        'yt-dlp',
        '--quiet',
        '--no-warnings',
        '--dateafter', 'now-4day',
        '--playlist-end', '5',
        '--impersonate', 'chrome',
        '--no-write-playlist-metafiles',
        '-f', formato,
        '-o', 'temp_media/%(id)s_%(playlist_index)02d.%(ext)s',
        url_tiktok
    ], capture_output=True)

# --- PROCESO PRINCIPAL ---
logger(f"--- 🛠️ INICIANDO SCAN ({len(USUARIOS)} cuentas) ---")
if not os.path.exists("temp_media"):
    os.makedirs("temp_media")

for i, user in enumerate(USUARIOS, 1):
    logger(f"\n👤 [Usuario #{i}] Procesando...")

    limpiar_temp()

    tiktok_user = user if user.startswith('@') else f'@{user}'
    user_hashtag = limpiar_hashtag(user)
    caption_tg = f'🎬 Nuevo de: <a href="https://www.tiktok.com/{tiktok_user}">{user}</a>\n\n#{user_hashtag}'
    url_base = f'https://www.tiktok.com/{tiktok_user}'

    # Cargar IDs ya procesados
    archive_ids = cargar_archive()

    # DESCARGA 1: vídeos normales
    logger("    ⬇️ Descargando vídeos...")
    descargar(url_base, 'mp4/bestvideo+bestaudio/best')

    # DESCARGA 2: carruseles (imágenes) — descarga aparte para no bloquearse con el archive
    logger("    ⬇️ Descargando carruseles...")
    descargar(url_base, 'jpg/jpeg/png/webp')

    # Filtrar archivos descargados
    archivos = [
        f for f in glob.glob("temp_media/*")
        if not f.lower().endswith(AUDIO_EXTS)
        and not f.lower().endswith(('.html', '.json'))
    ]

    if not archivos:
        logger("    ℹ️ Sin contenido nuevo")
        continue

    # Agrupar por ID y filtrar los ya procesados
    grupos = agrupar_archivos_por_id(archivos)
    grupos_nuevos = {vid_id: files for vid_id, files in grupos.items() if vid_id not in archive_ids}

    if not grupos_nuevos:
        logger("    ℹ️ Todo ya estaba en el archive")
        limpiar_temp()
        continue

    logger(f"    📂 {len(grupos_nuevos)} post(s) nuevo(s)")

    for vid_id, post_files in grupos_nuevos.items():
        post_files = sorted(post_files)
        logger(f"    🔍 Archivos: {[os.path.basename(f) for f in post_files]}")

        # Si hay mezcla de fotos y vídeo del mismo ID, priorizar fotos (es carrusel)
        fotos  = [f for f in post_files if f.lower().endswith(FOTO_EXTS)]
        videos = [f for f in post_files if f.lower().endswith(VIDEO_EXTS)]

        exito = False

        if fotos:
            if len(fotos) > 1:
                logger(f"    🖼️ Carrusel detectado ({len(fotos)} fotos)")
                exito = enviar_carrusel_completo(fotos, caption_tg)
            else:
                logger(f"    📷 Foto única detectada")
                exito = enviar_single("photo", fotos[0], caption_tg)
        elif videos:
            logger(f"    📦 Vídeo detectado")
            exito = enviar_single("video", videos[0], caption_tg)
        else:
            logger(f"    ⚠️ Formato no reconocido, saltando")
            exito = True

        if exito:
            logger("    ✅ Enviado con éxito")
            guardar_en_archive(vid_id)  # Solo marcamos como procesado si fue exitoso
        else:
            logger("    ❌ Error en el envío")

        for f in post_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

# Limpieza final
limpiar_temp()
logger("\n--- ✨ Fin del proceso ---")
