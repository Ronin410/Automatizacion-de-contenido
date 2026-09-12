# Correr la webapp en tu propia máquina Ubuntu (Docker)

Esto es para probarlo localmente — sin Caddy, sin dominio, accedés por
`http://localhost:8000`. Ideal para desarrollo/pruebas; para tenerlo
accesible desde el celu fuera de tu casa, seguí la guía de
`docs/deploy-oracle-cloud-free-tier.md` en cambio.

## 1. Instalar Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker          # o cerrá y volvé a abrir la terminal
docker compose version # confirma que el plugin de compose está
```

## 2. Traer el código

```bash
git clone https://github.com/Ronin410/Automatizacion-de-contenido
cd Automatizacion-de-contenido
git checkout claude/mejoras-optimizaciones-vb3w42   # o main, según a dónde se haya mergeado
```

## 3. Configurar

```bash
cp .env.example .env
cp config/settings.example.yaml config/settings.yaml
nano .env
```

Completá en `.env`:
- `GROQ_API_KEY` y `PEXELS_API_KEY` (ver el resto de la conversación/docs para conseguirlas).
- `WEBAPP_TOKEN`: cualquier string largo, ej. `openssl rand -hex 32`.
- `DOMINIO`: dejalo con el valor de ejemplo, no se usa (es solo para Caddy, que acá no corre).

Como estás en tu propia compu (más RAM que un tier gratis de la nube), en
`config/settings.yaml` podés dejar `whisper.modelo: small` y
`video.ancho/alto: 1080x1920` sin el ajuste a `tiny`/720x1280 que se
recomienda para hosting gratis con poca RAM.

## 4. Levantar

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build app
```

(`docker-compose.local.yml` solo agrega `ports: 8000:8000` para poder
entrar por `localhost` sin pasar por Caddy — ver el comentario en ese
archivo. No lo uses así en un servidor expuesto a internet.)

La primera build tarda varios minutos (instala ffmpeg + todas las
dependencias de Python). La primera vez que subas un audio, además,
`faster-whisper` descarga el modelo de Whisper (una sola vez).

## 5. Usarla

Abrí **http://localhost:8000**, pegá el `WEBAPP_TOKEN` que pusiste en `.env`, y listo.

## Operación del día a día

```bash
# ver logs en vivo
docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f app

# actualizar a la última versión del código
git pull
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build app

# apagar (la data en config/, history/, output_videos/, etc. queda en el disco)
docker compose -f docker-compose.yml -f docker-compose.local.yml down

# reiniciar
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d app
```

## Sin Docker (alternativa)

Si preferís no usar Docker en tu máquina, la CLI de siempre también sirve
sin webapp — ver `docs/pipeline-automatizacion-reels.md` §3.1 y el
`README`/setup de `requirements.txt` (`pip install -r requirements.txt`,
`python scripts/01_generate_script.py`, etc.).
