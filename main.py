import os
import json
import subprocess
import requests
import glob
import re
import shutil

# --- CONFIGURACIÓN ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
USUARIOS_RAW = os.getenv("LISTA_USUARIOS", "")
USUARIOS = [u.strip() for u in USUARIOS_RAW.replace('\n', ',').split(",") if u.strip()]

ARCHIVE = "archive.txt"

def logger(mensaje):
    print(f"[LOG] {mensaje}", flush=True)

def verificar_ffmpeg():
    path = shutil.which("ffmpeg")
    if path:
        logger("✅ Motor de vídeo detectado.")
        return True
    logger("❌ ERROR: FFmpeg no encontrado en el sistema.")
    return False

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

def tiene_stream_video(path):
    """Comprueba si un fichero tiene stream de vídeo real usando ffprobe."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_streams', '-select_streams', 'v', path],
            capture_output=True, text=True
        )
        return bool(result.stdout.strip())
    except:
        return False

def descargar_info_post(video_id):
    """
    Obtiene el JSON completo del post via yt-dlp.
    Prueba varias formas de URL por si una falla.
    """
    urls_a_probar = [
        f'https://www.tiktok.com/video/{video_id}',
        f'https://vm.tiktok.com/{video_id}',
        f'https://www.tiktok.com/@_/video/{video_id}',
    ]

    for url in urls_a_probar:
        result = subprocess.run([
            'yt-dlp', '--quiet', '--no-warnings',
            '--dump-json',
            '--impersonate', 'chrome',
            url
        ], capture_output=True, text=True)

        if result.returncode != 0 or not result.stdout.strip():
            continue

        try:
            info = json.loads(result.stdout)

            # yt-dlp puede usar distintos nombres según la versión
            images = (
                info.get('images') or
                info.get('image_urls') or
                info.get('thumbnails_carousel') or
                []
            )

            image_urls = []
            for img in images:
                if isinstance(img, dict):
                    url_img = (
                        img.get('url') or
                        img.get('thumbnail') or
                        img.get('original_url') or
                        ""
                    )
                    if url_img:
                        image_urls.append(url_img)
                elif isinstance(img, str):
                    image_urls.append(img)

            if image_urls:
                logger(f"   ✅ JSON OK: {len(image_urls)} imágenes encontradas.")
                return image_urls, True

        except json.JSONDecodeError:
            continue

    # Debug: volcar campos del JSON para diagnóstico
    logger(f"   🔍 Analizando estructura JSON del post...")
    result = subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--dump-json',
        '--impersonate', 'chrome',
        f'https://www.tiktok.com/video/{video_id}'
    ], capture_output=True, text=True)

    if result.stdout.strip():
        try:
            info = json.loads(result.stdout)
            # Filtrar campos que puedan contener nombres/URLs de usuario
            campos_seguros = [
                k for k in info.keys()
                if not any(x in k.lower() for x in ['uploader', 'channel', 'creator', 'author', 'url', 'webpage'])
            ]
            logger(f"   🔑 Campos disponibles: {campos_seguros}")
        except:
            logger(f"   ❌ JSON inválido recibido.")
    else:
        logger(f"   ❌ yt-dlp no devolvió datos.")

    return [], False

def crear_slideshow(video_id):
    logger(f"   📸 Carrusel detectado. Iniciando montaje...")

    output_video = f"temp_media/{video_id}_final.mp4"
    img_dir = f"temp_media/img_{video_id}"
    os.makedirs(img_dir, exist_ok=True)

    # 1. Obtener URLs de las imágenes del carrusel via JSON
    image_urls, es_carrusel = descargar_info_post(video_id)

    if not image_urls:
        logger(f"   ❌ No se encontraron imágenes en el JSON del post.")
        shutil.rmtree(img_dir, ignore_errors=True)
        return None

    # 2. Descargar imágenes directamente desde sus URLs
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
        except Exception as e:
            logger(f"   ⚠️ Error descargando imagen {idx}.")

    if not fotos:
        logger(f"   ❌ No se pudieron descargar las imágenes del carrusel.")
        shutil.rmtree(img_dir, ignore_errors=True)
        return None

    logger(f"   🖼️ {len(fotos)} imágenes descargadas. Descargando audio...")

    # 3. Descargar el audio por separado
    audio_path = f"temp_media/{video_id}_audio.m4a"
    subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '-f', 'bestaudio',
        '--impersonate', 'chrome',
        '-o', audio_path,
        f'https://www.tiktok.com/video/{video_id}'
    ], capture_output=True)

    tiene_audio = os.path.exists(audio_path)
    if not tiene_audio:
        logger("   ⚠️ Audio no disponible. El vídeo se creará sin sonido.")

    # 4. Renderizar con FFmpeg
    logger(f"   🎬 Renderizando slideshow...")
    try:
        list_file = f"temp_media/list_{video_id}.txt"
        with open(list_file, 'w') as f:
            for foto in fotos:
                f.write(f"file '{os.path.abspath(foto)}'\nduration 2.5\n")
            # Repetir la última foto para que el concat funcione correctamente
            f.write(f"file '{os.path.abspath(fotos[-1])}'\n")

        ffmpeg_cmd = [
            'ffmpeg', '-y', '-v', 'error',
            '-f', 'concat', '-safe', '0', '-i', list_file,
        ]

        if tiene_audio:
            ffmpeg_cmd += ['-i', audio_path]

        ffmpeg_cmd += [
            '-c:v', 'libx264', '-r', '30', '-pix_fmt', 'yuv420p',
            '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
        ]

        if tiene_audio:
            ffmpeg_cmd += ['-shortest']

        ffmpeg_cmd.append(output_video)
        subprocess.run(ffmpeg_cmd, check=True)

        # Limpieza de temporales del slideshow
        os.remove(list_file)
        shutil.rmtree(img_dir, ignore_errors=True)
        if tiene_audio and os.path.exists(audio_path):
            os.remove(audio_path)

        return output_video

    except Exception as e:
        logger(f"   ❌ Error FFmpeg al renderizar slideshow.")
        shutil.rmtree(img_dir, ignore_errors=True)
        return None

def procesar_descarga(tiktok_url):
    logger("🚀 Escaneando actividad reciente...")
    subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--dateafter', 'now-2day', '--playlist-end', '5',
        '--impersonate', 'chrome',
        '-f', 'bestvideo+bestaudio/best', '--merge-output-format', 'mp4',
        '-o', 'temp_media/%(id)s.%(ext)s',
        tiktok_url
    ], capture_output=True)

# --- EJECUCIÓN ---
verificar_ffmpeg()
limpiar_temp()
archive_ids = cargar_archive()

for i, user in enumerate(USUARIOS, 1):
    logger(f"\n👤 [Cuenta #{i}/{len(USUARIOS)}]")
    tiktok_user = user if user.startswith('@') else f'@{user}'
    user_hashtag = re.sub(r'[^a-zA-Z0-9_]', '_', user.lstrip('@'))
    caption_tg = f'🎬 Nuevo de: <a href="https://www.tiktok.com/{tiktok_user}">{user}</a>\n\n#{user_hashtag}'

    procesar_descarga(f'https://www.tiktok.com/{tiktok_user}')

    # Recopilar IDs únicos de los ficheros descargados
    ficheros = glob.glob("temp_media/*")
    ids_en_temp = set(
        os.path.basename(f).split('.')[0].split('_')[0]
        for f in ficheros
    )

    enviados_cuenta = 0
    for vid_id in ids_en_temp:
        if vid_id in archive_ids:
            logger(f"   ⏭️ Post ya archivado, saltando.")
            for f in glob.glob(f"temp_media/{vid_id}*"):
                try:
                    os.remove(f)
                except:
                    pass
            continue

        video_final = None
        path_mp4 = f"temp_media/{vid_id}.mp4"

        if os.path.exists(path_mp4):
            if tiene_stream_video(path_mp4):
                logger(f"   🎥 Post detectado como vídeo.")
                video_final = path_mp4
            else:
                logger(f"   🖼️ Post detectado como carrusel (mp4 sin stream de vídeo).")
                os.remove(path_mp4)
                video_final = crear_slideshow(vid_id)
        else:
            logger(f"   🖼️ Sin mp4, intentando como carrusel.")
            video_final = crear_slideshow(vid_id)

        if video_final and os.path.exists(video_final):
            logger(f"   📦 Enviando fichero ({os.path.getsize(video_final) // 1024} KB)...")
            if enviar_video(video_final, caption_tg):
                guardar_en_archive(vid_id)
                archive_ids.add(vid_id)
                enviados_cuenta += 1
                logger(f"   ✅ Post enviado y archivado.")
            else:
                logger(f"   ❌ Fallo al enviar a Telegram.")
        else:
            logger(f"   ⚠️ No se pudo procesar el post.")

        # Limpieza de cualquier residuo de este post
        for f in glob.glob(f"temp_media/{vid_id}*"):
            try:
                os.remove(f)
            except:
                pass

    logger(f"📊 Resumen: {enviados_cuenta} nuevos enviados.")

logger("\n--- ✨ Proceso completado ---")
