import os
import json
import subprocess
import requests
import glob
import re
import shutil
import time

# --- CONFIGURACIÓN ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
USUARIOS_RAW = os.getenv("LISTA_USUARIOS", "")
USUARIOS = [u.strip() for u in USUARIOS_RAW.replace('\n', ',').split(",") if u.strip()]

ARCHIVE = "archive.txt"
DELAY_REINTENTO = 8  # segundos entre reintentos de gallery-dl

def logger(mensaje):
    print(f"[LOG] {mensaje}", flush=True)

def verificar_dependencias():
    for tool in ["ffmpeg", "ffprobe", "yt-dlp", "gallery-dl"]:
        if shutil.which(tool):
            logger(f"✅ {tool} detectado.")
        else:
            logger(f"❌ ERROR: {tool} no encontrado.")

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

def enviar_album_fotos(fotos, caption):
    """
    Envía una lista de fotos como álbum de Telegram (sendMediaGroup).
    Divide en paquetes de máximo 10. El caption solo va en la primera foto.
    Devuelve True si todos los paquetes se enviaron bien.
    """
    url = f"https://api.telegram.org/bot{TOKEN}/sendMediaGroup"

    # Dividir en paquetes de 10
    paquetes = [fotos[i:i+10] for i in range(0, len(fotos), 10)]
    total_paquetes = len(paquetes)

    for idx_paquete, paquete in enumerate(paquetes):
        logger(f"   📤 Enviando álbum {idx_paquete+1}/{total_paquetes} ({len(paquete)} fotos)...")

        media = []
        files = {}

        for idx, foto_path in enumerate(paquete):
            file_key = f"photo_{idx}"
            # Solo el primer foto del primer paquete lleva caption
            if idx == 0 and idx_paquete == 0:
                media.append({
                    "type": "photo",
                    "media": f"attach://{file_key}",
                    "caption": caption,
                    "parse_mode": "HTML"
                })
            else:
                media.append({
                    "type": "photo",
                    "media": f"attach://{file_key}"
                })
            files[file_key] = open(foto_path, 'rb')

        try:
            r = requests.post(
                url,
                data={'chat_id': CHAT_ID, 'media': json.dumps(media)},
                files=files
            )
            ok = r.status_code == 200
            if not ok:
                logger(f"   ❌ Error enviando álbum: {r.text[:200]}")
        except Exception as e:
            logger(f"   ❌ Excepción enviando álbum.")
            ok = False
        finally:
            for f in files.values():
                f.close()

        if not ok:
            return False

        # Pequeña pausa entre paquetes para no saturar la API
        if idx_paquete < total_paquetes - 1:
            time.sleep(1)

    return True

def tiene_stream_video(path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_streams', '-select_streams', 'v', path],
            capture_output=True, text=True
        )
        return bool(result.stdout.strip())
    except:
        return False

def es_post_carrusel(post_url):
    result = subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--dump-json', '--impersonate', 'chrome',
        post_url
    ], capture_output=True, text=True)

    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        info = json.loads(result.stdout)
        if info.get('images'):
            return True
        for fmt in (info.get('formats') or []):
            if fmt.get('vcodec') and fmt['vcodec'] != 'none':
                return False
        return None
    except:
        return None

def descargar_video_directo(video_id, post_url):
    out_path = f"temp_media/{video_id}.mp4"
    subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--impersonate', 'chrome',
        '-f', 'bestvideo+bestaudio/best', '--merge-output-format', 'mp4',
        '-o', out_path, post_url
    ], capture_output=True)

    if os.path.exists(out_path) and tiene_stream_video(out_path):
        return out_path
    if os.path.exists(out_path):
        os.remove(out_path)
    return None

def descargar_imagenes_gallerydl(img_dir, post_url):
    """Intenta descargar imágenes con gallery-dl, con un reintento."""
    for intento in range(1, 3):
        if intento > 1:
            logger(f"   🔄 Reintento {intento} con gallery-dl (espera {DELAY_REINTENTO}s)...")
            time.sleep(DELAY_REINTENTO)

        subprocess.run([
            'gallery-dl', '--quiet', '-D', img_dir, post_url
        ], capture_output=True, text=True)

        fotos = []
        for ext in ('*.jpg', '*.jpeg', '*.png', '*.webp', '*.JPG', '*.PNG'):
            fotos.extend(glob.glob(os.path.join(img_dir, ext)))
        fotos = sorted(set(fotos))

        if fotos:
            logger(f"   🖼️ {len(fotos)} imágenes obtenidas con gallery-dl.")
            return fotos

    return []

def descargar_imagenes_ytdlp(img_dir, post_url):
    """Fallback: extrae URLs del JSON de yt-dlp y descarga con requests."""
    logger(f"   🔄 Fallback: extrayendo imágenes desde yt-dlp JSON...")
    result = subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--dump-json', '--impersonate', 'chrome',
        post_url
    ], capture_output=True, text=True)

    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        info = json.loads(result.stdout)
        images = info.get('images') or []
        image_urls = []
        for img in images:
            if isinstance(img, dict):
                url = img.get('url') or img.get('thumbnail') or img.get('original_url') or ''
                if url:
                    image_urls.append(url)
            elif isinstance(img, str):
                image_urls.append(img)

        if not image_urls:
            logger(f"   ⚠️ JSON no contiene imágenes.")
            return []

        fotos = []
        for idx, img_url in enumerate(image_urls):
            dest = os.path.join(img_dir, f"{idx:03d}.jpg")
            try:
                r = requests.get(img_url, timeout=15, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': 'https://www.tiktok.com/'
                })
                if r.status_code == 200:
                    with open(dest, 'wb') as f:
                        f.write(r.content)
                    fotos.append(dest)
            except:
                pass

        if fotos:
            logger(f"   🖼️ {len(fotos)} imágenes obtenidas con fallback yt-dlp.")
        else:
            logger(f"   ⚠️ Fallback yt-dlp tampoco obtuvo imágenes.")
        return fotos
    except:
        return []

def procesar_carrusel(video_id, post_url, caption):
    """
    Descarga las imágenes del carrusel y las envía como álbum(es) de Telegram.
    No genera ningún vídeo — es mucho más rápido.
    """
    logger(f"   📸 Procesando carrusel como álbum de fotos...")

    img_dir = f"temp_media/img_{video_id}"
    os.makedirs(img_dir, exist_ok=True)

    # Intentar gallery-dl primero, luego fallback yt-dlp
    logger(f"   📥 Descargando imágenes...")
    fotos = descargar_imagenes_gallerydl(img_dir, post_url)
    if not fotos:
        fotos = descargar_imagenes_ytdlp(img_dir, post_url)

    if not fotos:
        logger(f"   ❌ No se pudieron obtener imágenes del carrusel.")
        shutil.rmtree(img_dir, ignore_errors=True)
        return False

    logger(f"   📨 Enviando {len(fotos)} fotos en álbum(es)...")
    ok = enviar_album_fotos(fotos, caption)

    shutil.rmtree(img_dir, ignore_errors=True)
    return ok

def obtener_ids_recientes(tiktok_url):
    result = subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--dateafter', 'now-2day', '--playlist-end', '5',
        '--impersonate', 'chrome',
        '--skip-download', '--print', '%(id)s',
        tiktok_url
    ], capture_output=True, text=True)
    return [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]

def descargar_videos_bulk(tiktok_url):
    logger("🚀 Descargando contenido reciente...")
    subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--dateafter', 'now-2day', '--playlist-end', '5',
        '--impersonate', 'chrome',
        '-f', 'bestvideo+bestaudio/best', '--merge-output-format', 'mp4',
        '-o', 'temp_media/%(id)s.%(ext)s',
        tiktok_url
    ], capture_output=True)

# --- EJECUCIÓN ---
verificar_dependencias()
limpiar_temp()
archive_ids = cargar_archive()

for i, user in enumerate(USUARIOS, 1):
    logger(f"\n👤 [Cuenta #{i}/{len(USUARIOS)}]")
    tiktok_user = user if user.startswith('@') else f'@{user}'
    user_hashtag = re.sub(r'[^a-zA-Z0-9_]', '_', user.lstrip('@'))
    caption_tg = f'🎬 Nuevo de: <a href="https://www.tiktok.com/{tiktok_user}">{user}</a>\n\n#{user_hashtag}'
    tiktok_url = f'https://www.tiktok.com/{tiktok_user}'

    ids_recientes = obtener_ids_recientes(tiktok_url)
    id_url_map = {
        vid_id: f'https://www.tiktok.com/{tiktok_user}/video/{vid_id}'
        for vid_id in ids_recientes
    }

    descargar_videos_bulk(tiktok_url)

    ids_en_temp = set(
        os.path.basename(f).split('.')[0].split('_')[0]
        for f in glob.glob("temp_media/*")
    )
    ids_a_procesar = ids_en_temp | set(id_url_map.keys())

    enviados_cuenta = 0
    for vid_id in ids_a_procesar:
        if vid_id in archive_ids:
            logger(f"   ⏭️ Post ya archivado, saltando.")
            for f in glob.glob(f"temp_media/{vid_id}*"):
                try: os.remove(f)
                except: pass
            continue

        post_url = id_url_map.get(vid_id, f'https://www.tiktok.com/video/{vid_id}')
        enviado = False
        path_mp4 = f"temp_media/{vid_id}.mp4"

        if os.path.exists(path_mp4) and tiene_stream_video(path_mp4):
            # Vídeo normal
            logger(f"   🎥 Post detectado como vídeo.")
            if enviar_video(path_mp4, caption_tg):
                enviado = True
            else:
                logger(f"   ❌ Fallo al enviar vídeo a Telegram.")
        else:
            if os.path.exists(path_mp4):
                os.remove(path_mp4)

            logger(f"   🔍 Consultando tipo de post...")
            tipo = es_post_carrusel(post_url)

            if tipo is True:
                logger(f"   🖼️ Confirmado como carrusel.")
                if procesar_carrusel(vid_id, post_url, caption_tg):
                    enviado = True

            elif tipo is False:
                logger(f"   🎥 Confirmado como vídeo. Reintentando descarga...")
                path = descargar_video_directo(vid_id, post_url)
                if path and enviar_video(path, caption_tg):
                    enviado = True
                else:
                    logger(f"   ❌ No se pudo descargar/enviar el vídeo.")

            else:
                # Tipo desconocido: intentar vídeo, luego carrusel
                logger(f"   ❓ Tipo desconocido. Intentando como vídeo...")
                path = descargar_video_directo(vid_id, post_url)
                if path and enviar_video(path, caption_tg):
                    enviado = True
                else:
                    logger(f"   🖼️ Vídeo fallido, intentando como carrusel...")
                    if procesar_carrusel(vid_id, post_url, caption_tg):
                        enviado = True

        if enviado:
            guardar_en_archive(vid_id)
            archive_ids.add(vid_id)
            enviados_cuenta += 1
            logger(f"   ✅ Post enviado y archivado.")
        else:
            logger(f"   ⚠️ No se pudo procesar el post.")

        for f in glob.glob(f"temp_media/{vid_id}*"):
            try: os.remove(f)
            except: pass

    logger(f"📊 Resumen: {enviados_cuenta} nuevos enviados.")

logger("\n--- ✨ Proceso completado ---")
