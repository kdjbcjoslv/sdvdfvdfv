# 1. Usar una imagen oficial de Python ligera como base
FROM python:3.1 1

# 2. Variables de entorno para que Python no guarde basura y los logs se vean bien en GitHub Actions
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3. Instalar FFmpeg y limpiar la caché de Linux para que la imagen pese lo menos posible
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 4. Instalar tus librerías de Python (sin guardar caché para ahorrar espacio)
RUN pip install --no-cache-dir yt-dlp requests curl-cffi gallery-dl

# 5. Establecer la carpeta de trabajo por defecto
WORKDIR /app
