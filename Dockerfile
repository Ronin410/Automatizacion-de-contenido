FROM python:3.11-slim

# ffmpeg como respaldo a nivel sistema: moviepy/imageio-ffmpeg suele traer su
# propio binario, pero tenerlo instalado evita sorpresas en algunas plataformas/arquitecturas (ej. ARM).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-webapp.txt ./
RUN pip install --no-cache-dir -r requirements-webapp.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "8000"]
