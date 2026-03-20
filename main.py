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

def verificar_dependencias():
    ok = True
    for tool in ["ffmpeg", "ffprobe", "yt-dlp", "gallery-dl"]:
        if shutil.which(tool):
            logger(f"✅ {tool} detectado.")
        else:
            logger(f"❌ ERROR: {tool} no encontrado en el sistema.")
            ok = False
    return ok

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

def descargar_carrusel_gallerydl(video_id, post_url):
    """
    Usa gallery-dl para descargar las imágenes del carrusel directamente.
    Es más fiable que yt-dlp para este tipo de contenido.
    """
    img_dir = f"temp_media/img_{video_id}"
    os.makedirs(img_dir, exist_ok=True)

    logger(f"   📥 Descargando imágenes con gallery-dl...")

    result = subprocess.run([
        'gallery-dl',
        '--quiet',
        '-D', img_dir,
        post_url
    ], capture_output=True, text=True)

    # Recoger imágenes descargadas
    fotos = []
    for ext in ('*.jpg', '*.jpeg', '*.png', '*.webp', '*.JPG', '*.PNG'):
        fotos.extend(glob.glob(os.path.join(img_dir, ext)))
    fotos = sorted(set(fotos))

    if not fotos:
        logger(f"   ⚠️ gallery-dl no descargó imágenes. stderr: {result.stderr[:200] if result.stderr else 'vacío'}")
        shutil.rmtree(img_dir, ignore_errors=True)
        return None, None

    logger(f"   🖼️ {len(fotos)} imágenes descargadas.")
    return fotos, img_dir

def crear_slideshow(video_id, post_url):
    logger(f"   📸 Carrusel detectado. Iniciando montaje...")

    output_video = f"temp_media/{video_id}_final.mp4"

    # 1. Descargar imágenes con gallery-dl
    fotos, img_dir = descargar_carrusel_gallerydl(video_id, post_url)

    if not fotos:
        logger(f"   ❌ No se pudieron obtener imágenes del carrusel.")
        return None

    # 2. Descargar audio con yt-dlp
    audio_path = f"temp_media/{video_id}_audio.m4a"
    logger(f"   🎵 Descargando audio...")
    subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '-f', 'bestaudio',
        '--impersonate', 'chrome',
        '-o', audio_path,
        post_url
    ], capture_output=True)

    tiene_audio = os.path.exists(audio_path)
    if not tiene_audio:
        logger("   ⚠️ Audio no disponible. El vídeo se creará sin sonido.")

    # 3. Renderizar con FFmpeg
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

        # Limpieza
        os.remove(list_file)
        shutil.rmtree(img_dir, ignore_errors=True)
        if tiene_audio and os.path.exists(audio_path):
            os.remove(audio_path)

        return output_video

    except Exception as e:
        logger(f"   ❌ Error FFmpeg al renderizar slideshow.")
        shutil.rmtree(img_dir, ignore_errors=True)
        return None

def procesar_descarga(tiktok_url, user_slug):
    """
    Descarga los posts recientes y devuelve un mapeo {video_id: post_url}.
    Usamos --print para capturar los IDs sin necesidad de parsear ficheros.
    """
    logger("🚀 Escaneando actividad reciente...")
    result = subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--dateafter', 'now-2day', '--playlist-end', '5',
        '--impersonate', 'chrome',
        '-f', 'bestvideo+bestaudio/best', '--merge-output-format', 'mp4',
        '--print', '%(id)s',
        '-o', 'temp_media/%(id)s.%(ext)s',
        tiktok_url
    ], capture_output=True, text=True)

    id_url_map = {}
    for vid_id in result.stdout.strip().splitlines():
        vid_id = vid_id.strip()
        if vid_id:
            id_url_map[vid_id] = f'https://www.tiktok.com/{user_slug}/video/{vid_id}'

    return id_url_map

# --- EJECUCIÓN ---
verificar_dependencias()
limpiar_temp()
archive_ids = cargar_archive()

for i, user in enumerate(USUARIOS, 1):
    logger(f"\n👤 [Cuenta #{i}/{len(USUARIOS)}]")
    tiktok_user = user if user.startswith('@') else f'@{user}'
    user_hashtag = re.sub(r'[^a-zA-Z0-9_]', '_', user.lstrip('@'))
    caption_tg = f'🎬 Nuevo de: <a href="https://www.tiktok.com/{tiktok_user}">{user}</a>\n\n#{user_hashtag}'

    id_url_map = procesar_descarga(f'https://www.tiktok.com/{tiktok_user}', tiktok_user)

    # IDs encontrados en disco + IDs reportados por yt-dlp (carruseles que no generan mp4)
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
                try:
                    os.remove(f)
                except:
                    pass
            continue

        # URL real del post para gallery-dl y yt-dlp
        post_url = id_url_map.get(vid_id, f'https://www.tiktok.com/video/{vid_id}')

        video_final = None
        path_mp4 = f"temp_media/{vid_id}.mp4"

        if os.path.exists(path_mp4):
            if tiene_stream_video(path_mp4):
                logger(f"   🎥 Post detectado como vídeo.")
                video_final = path_mp4
            else:
                logger(f"   🖼️ Post detectado como carrusel (mp4 sin stream de vídeo).")
                os.remove(path_mp4)
                video_final = crear_slideshow(vid_id, post_url)
        else:
            logger(f"   🖼️ Sin mp4, intentando como carrusel.")
            video_final = crear_slideshow(vid_id, post_url)

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

        # Limpieza de residuos del post
        for f in glob.glob(f"temp_media/{vid_id}*"):
            try:
                os.remove(f)
            except:
                pass

    logger(f"📊 Resumen: {enviados_cuenta} nuevos enviados.")

logger("\n--- ✨ Proceso completado ---")
