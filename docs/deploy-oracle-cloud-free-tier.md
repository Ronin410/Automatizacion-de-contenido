# Desplegar la webapp en una VM siempre gratis (Oracle Cloud Free Tier)

Esta guía deja el pipeline corriendo 24/7 en internet, gratis, sin depender
de tu computadora. Accedés desde cualquier navegador (celu incluido),
pedís el guion, lo elegís, subís el audio grabado, y descargás el video
final cuando está listo.

**Por qué esta opción y no Render/Railway (tiers gratis típicos):** Whisper
y MoviePy necesitan bastante RAM y CPU sostenida por varios minutos. Los
tiers gratuitos de la mayoría de PaaS tienen RAM chica (512MB-1GB), matan
requests largos, y borran el disco en cada redeploy. Oracle Cloud ofrece
una VM real (hasta 4 OCPU ARM + 24GB RAM) **gratis para siempre**, sin esos
límites — la contra es que hay que configurar el servidor una vez a mano.

> Nota: los pasos exactos de la consola de Oracle Cloud pueden variar con el
> tiempo; si algún menú no coincide 1:1, buscá el equivalente (los nombres
> generales — "Always Free", "Compute", "Instance" — se mantienen).

## 1. Crear la cuenta y la VM

1. Creá una cuenta en [cloud.oracle.com](https://cloud.oracle.com) (pide tarjeta para verificar identidad, pero los recursos "Always Free" no cobran mientras te quedes dentro de esos límites).
2. Consola → **Compute → Instances → Create Instance**.
3. Imagen: **Ubuntu 22.04** (o la LTS más reciente disponible).
4. Forma (shape): elegí una marcada **"Always Free"**:
   - Preferí **VM.Standard.A1.Flex** (ARM/Ampere) con 2-4 OCPU y 12-24GB RAM — es la que da más margen para Whisper+MoviePy.
   - Si esa no está disponible en tu región/cuenta, la alternativa **VM.Standard.E2.1.Micro** (AMD, 1GB RAM) también es siempre gratis, pero vas a tener que usar el modelo `tiny` de Whisper y esperar más por cada video.
5. Al crear, guardá la clave SSH privada que te ofrece descargar (la vas a necesitar para conectarte).
6. Anotá la **IP pública** que le asigna a la instancia.

## 2. Abrir los puertos 80 y 443

Hay dos capas de firewall que hay que abrir, las dos:

**A) Security List de la subred** (en la consola de Oracle):
Networking → Virtual Cloud Networks → tu VCN → Security Lists → agregar Ingress Rules para los puertos **80** y **443** (TCP, origen 0.0.0.0/0).

**B) Firewall del sistema operativo** (dentro de la VM, por SSH):
```bash
ssh -i tu_clave.pem ubuntu@TU_IP_PUBLICA

sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save   # si no existe, instalalo: sudo apt install -y iptables-persistent
```

## 3. Instalar Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker   # o cerrá y volvé a abrir la sesión SSH
docker compose version   # confirma que el plugin de compose está incluido
```

## 4. Traer el código

```bash
git clone https://github.com/Ronin410/Automatizacion-de-contenido
cd Automatizacion-de-contenido
git checkout claude/mejoras-optimizaciones-vb3w42   # o main, según a dónde se haya mergeado
```

## 5. Configurar API keys, token y dominio

```bash
cp .env.example .env
cp config/settings.example.yaml config/settings.yaml
nano .env
```

Completá en `.env`:
- `GROQ_API_KEY` y `PEXELS_API_KEY` (ver docs para conseguirlas).
- `WEBAPP_TOKEN`: generá uno random con `openssl rand -hex 32` y pegalo.
- `DOMINIO`: si no tenés dominio propio, usá el truco de **nip.io** — convierte tu IP pública en un hostname válido gratis. Si tu IP es `123.45.67.89`, tu dominio es `123-45-67-89.nip.io`. Caddy le va a poder pedir un certificado HTTPS real de Let's Encrypt a ese hostname sin que pagues nada.

## 6. Levantar todo

```bash
docker compose up -d --build
docker compose logs -f app   # Ctrl+C para dejar de seguir el log (los contenedores siguen corriendo)
```

La primera vez que subas un audio, `faster-whisper` va a descargar el modelo (una sola vez, después queda cacheado en el volumen).

## 7. Usarla

Abrí `https://TU_DOMINIO` (el mismo que pusiste en `DOMINIO`) desde cualquier navegador. Pegá el `WEBAPP_TOKEN` en el campo de arriba y ya podés generar guiones, elegir uno, subir tu narración grabada, y descargar el video cuando esté listo.

## Operación del día a día

```bash
# ver logs en vivo
docker compose logs -f app

# actualizar a la última versión del código
git pull
docker compose up -d --build

# apagar todo (la data en config/, history/, output_videos/, etc. queda intacta en el disco)
docker compose down

# reiniciar
docker compose up -d
```

## Límites a tener en cuenta

- El plan **"Always Free"** de Oracle tiene un tope total de OCPU/RAM/almacenamiento gratis por cuenta — mientras esta sea la única VM que uses, no debería haber cobros, pero revisá el detalle actualizado en la consola de Oracle (Billing → Cost Management) antes de asumir que es 100% gratis para siempre en tu caso puntual.
- Solo un video se procesa a la vez (a propósito, para no quedarte sin RAM); si subís un segundo audio mientras el primero se procesa, queda en cola.
- El estado de los trabajos en curso vive en memoria: si reiniciás el contenedor (`docker compose restart`) mientras algo se está procesando, ese trabajo se pierde (pero podés volver a subir el mismo audio).
- Esto **no reemplaza HTTPS por un dominio propio** de forma perfecta: nip.io funciona bien para uso personal, pero si en algún momento comprás un dominio real, solo hay que cambiar `DOMINIO` en `.env` y correr `docker compose up -d` de nuevo.
