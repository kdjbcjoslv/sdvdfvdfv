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
DURACION_POR_FOTO = 3.5  # segundos por imagen en el slideshow

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

def obtener_duracion_audio(path):
    """Devuelve la duración en segundos de un fichero de audio."""
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'quiet',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            path
        ], capture_output=True, text=True)
        return float(result.stdout.strip())
    except:
        return None

def descargar_carrusel_gallerydl(video_id, post_url):
    """
    Usa gallery-dl para descargar las imágenes del carrusel directamente.
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

    fotos = []
    for ext in ('*.jpg', '*.jpeg', '*.png', '*.webp', '*.JPG', '*.PNG'):
        fotos.extend(glob.glob(os.path.join(img_dir, ext)))
    fotos = sorted(set(fotos))

    if not fotos:
        logger(f"   ⚠️ gallery-dl no descargó imágenes.")
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

    # 3. Calcular duración por foto para cubrir todo el audio
    dur_por_foto = DURACION_POR_FOTO
    if tiene_audio:
        dur_audio = obtener_duracion_audio(audio_path)
        if dur_audio and len(fotos) > 0:
            # Distribuir el audio entre todas las fotos equitativamente
            dur_por_foto = max(DURACION_POR_FOTO, dur_audio / len(fotos))
            logger(f"   ⏱️ Audio: {dur_audio:.1f}s → {dur_por_foto:.1f}s por foto.")

    # 4. Renderizar con FFmpeg
    logger(f"   🎬 Renderizando slideshow...")
    try:
        list_file = f"temp_media/list_{video_id}.txt"
        with open(list_file, 'w') as f:
            for foto in fotos:
                f.write(f"file '{os.path.abspath(foto)}'\nduration {dur_por_foto}\n")
            # Repetir la última foto (requerido por ffmpeg concat)
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
            # Usar el audio como referencia de duración final
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

def obtener_ids_recientes(tiktok_url):
    """
    Paso 1: solo obtener los IDs de los posts recientes sin descargar nada.
    """
    result = subprocess.run([
        'yt-dlp', '--quiet', '--no-warnings',
        '--dateafter', 'now-6day', '--playlist-end', '20',
        '--impersonate', 'chrome',
        '--skip-download',
        '--print', '%(id)s',
        tiktok_url
    ], capture_output=True, text=True)

    ids = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    return ids

def descargar_videos(tiktok_url):
    """
    Paso 2: descargar los ficheros reales (vídeos y audio de carruseles).
    """
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

    # Paso 1: obtener IDs para construir URLs reales de cada post
    ids_recientes = obtener_ids_recientes(tiktok_url)
    id_url_map = {vid_id: f'https://www.tiktok.com/{tiktok_user}/video/{vid_id}' for vid_id in ids_recientes}

    # Paso 2: descargar ficheros
    descargar_videos(tiktok_url)

    # Combinar IDs en disco + IDs reportados (carruseles sin mp4)
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
