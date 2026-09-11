# Pipeline de Automatización de Contenido — Reels/Shorts (YouTube + Facebook)

> **v2** — Documento de diseño revisado. Se resolvieron las preguntas abiertas de la v1 y se incorporaron mejoras (selección interactiva de guion, validación de duración, manejo de errores, watcher automático e historial de temas). Los cambios respecto a la v1 están marcados con 🆕.
>
> **v3** — Se agregó una webapp (`webapp/`) para poder usar el pipeline sin depender de la computadora local: pedís el guion, elegís candidato, subís el audio grabado y descargás el video, todo desde el navegador (celu incluido). Pensada para desplegarse en una VM siempre gratis (ver `docs/deploy-oracle-cloud-free-tier.md`). Ver §11.

## 1. Objetivo del proyecto

Crear una herramienta en Python que automatice la mayor parte del flujo de creación de videos cortos (reels/shorts) para un canal de YouTube y página de Facebook, en los nichos de **tecnología, programación, videojuegos y películas**, minimizando el tiempo de producción manual (ideas, guion, voz, imágenes, edición).

## 2. Restricciones clave

- **Sin presupuesto de nube pagado.** Usar únicamente APIs con tier gratuito, herramientas open-source, o procesamiento local.
- El usuario tiene poco tiempo disponible: el sistema debe requerir mínima intervención manual una vez configurado.
- El usuario **narrará con su propia voz** (no TTS sintético) para cumplir con la política de "contenido auténtico" de YouTube — evitar que el canal se marque como contenido inauténtico/repetitivo. Si en el futuro se usa voz sintética, debe activarse el disclosure de "contenido alterado o sintético" en la subida.
- Formato objetivo: videos verticales cortos (~60-90s), aptos para YouTube Shorts y Facebook Reels.

## 3. Pipeline propuesto

| Etapa | Descripción | Herramienta sugerida | Costo |
|---|---|---|---|
| 1. Generación de idea/guion | El usuario da un tema/idea opcional (o se usa rotación de nicho); el LLM genera **varias opciones de guion** y el usuario elige una 🆕 | **Groq API (Llama, gratis)** 🆕 | Gratis |
| 2. Grabación de voz | El usuario graba su narración leyendo el guion elegido | Grabación local (micrófono) | Gratis |
| 3. Transcripción/subtítulos | Genera subtítulos sincronizados a partir del audio grabado | Whisper local (`faster-whisper`) | Gratis (CPU) |
| 4. Búsqueda de B-roll/imágenes | Busca clips/imágenes relacionadas a palabras clave del guion | Pexels API / Pixabay API | Gratis |
| 5. Ensamblado de video | Combina audio + clips + subtítulos + intro/outro | MoviePy / FFmpeg | Gratis (local) |
| 6. Revisión manual | Carpeta de salida para que el usuario revise antes de publicar | Sistema de archivos local | — |
| 7. Publicación (opcional, fase posterior) | Subida automática a YouTube/Facebook | YouTube Data API v3 / Facebook Graph API | Gratis (con límites de cuota) |

### 3.1 Flujo de ejecución (dos scripts, con pausa manual para grabar)

El pipeline se ejecuta en dos pasos separados, con una pausa real en medio para que el usuario grabe su voz:

1. **`python 01_generate_script.py [--idea "texto libre opcional"]`** 🆕
   - Si se pasa `--idea`, el guion gira alrededor de ese tema puntual (dentro del nicho que corresponda o del nicho indicado con `--nicho`).
   - Si no se pasa `--idea`, se usa la rotación fija de nicho (tech / programación / gaming / películas) como en la v1.
   - Llama a Groq y genera **N candidatos** (por defecto 3, configurable) en vez de un único guion.
   - Para cada candidato calcula la **duración estimada de narración** (palabras ÷ palabras-por-minuto configuradas) y descarta o marca en rojo los que caen fuera del rango objetivo (60-90s por defecto).
   - Muestra los candidatos numerados en pantalla con su duración estimada y palabras clave detectadas, y pide al usuario elegir uno (o regenerar si ninguno convence). Esto sigue siendo una sola ejecución corta — no es la pausa larga de grabación, así que no rompe el flujo de "dos comandos" de la v1.
   - Antes de generar, consulta el **historial** (`history/historial_guiones.json`) para evitar repetir el mismo subtema reciente dentro del mismo nicho. 🆕
   - Guarda el guion elegido en `output/guion_del_dia.txt` y registra la elección (fecha, nicho, idea, duración estimada) en el historial. 🆕
   - Termina — no se queda esperando en la misma ejecución.

2. **Pausa manual (fuera del script)**
   - El usuario lee el guion generado y graba su narración con cualquier herramienta (celular, Audacity, etc.).
   - Guarda el archivo de audio en `input_audio/` (nombre esperado o el más reciente por timestamp).
   - **Alternativa opcional:** correr `python watch_audio.py` en una terminal aparte antes de grabar; detecta automáticamente el nuevo archivo en `input_audio/` y dispara `02_finalizar.py` solo, sin que el usuario tenga que volver a la terminal. 🆕 (Adelanta parte de lo que la v1 dejaba para "Fase 2".)

3. **`python 02_finalizar.py`**
   - Detecta el archivo de audio más reciente en `input_audio/`.
   - Corre Whisper para transcribir y generar subtítulos sincronizados.
   - Busca B-roll relevante según palabras clave del guion original.
   - Ensambla el video final con MoviePy (audio + clips + subtítulos + intro/outro).
   - Deja el resultado en `output_videos/` listo para revisión.
   - Cada etapa (Groq, Whisper, Pexels/Pixabay, MoviePy) queda envuelta en reintentos con backoff y logging a `logs/` (ver §6 y §9). 🆕 Si una etapa falla después de reintentar, el script se detiene con un mensaje claro de qué falló y qué archivo intermedio quedó a medio hacer, en vez de fallar silenciosamente o dejar un video corrupto en `output_videos/`.

Esta separación en dos comandos (en vez de un único script con `input()` a mitad de camino) evita que el proceso quede "colgado" esperando en la terminal, y es más fácil de depurar paso a paso con Claude Code. El watcher opcional de arriba resuelve el mismo problema que proponía la v1 para una "versión posterior (Fase 2)", pero ya como parte del MVP, porque es una mejora pequeña y de bajo riesgo.

## 4. Arquitectura de carpetas sugerida

```
content-pipeline/
├── config/
│   └── settings.yaml          # nichos, claves de API, parámetros de video, umbrales de duración
├── scripts/
│   ├── 01_generate_script.py  # genera N guiones candidatos vía Groq y deja elegir uno
│   ├── 02_transcribe.py       # Whisper sobre el audio grabado por el usuario
│   ├── 03_fetch_broll.py      # busca clips/imágenes en Pexels/Pixabay
│   ├── 04_assemble_video.py   # MoviePy: junta todo
│   ├── 05_publish.py          # (fase 2) sube a YouTube/Facebook
│   └── watch_audio.py         # 🆕 (opcional) dispara 02_finalizar.py al detectar audio nuevo
├── common/                    # 🆕
│   ├── llm_client.py          # wrapper de Groq con reintentos/backoff
│   ├── logging_config.py      # configuración centralizada de logging
│   └── history.py             # lectura/escritura de history/historial_guiones.json
├── assets/
│   ├── intro_outro/           # clips fijos reutilizables
│   └── fonts/                 # tipografía para subtítulos
├── input_audio/                # narraciones grabadas por el usuario
├── output/
│   └── guion_del_dia.txt
├── output_videos/              # videos listos para revisión
├── history/                    # 🆕 historial_guiones.json (temas ya usados, duración, fecha)
├── logs/                       # 🆕 logs con timestamp por ejecución
└── requirements.txt
```

## 5. Stack técnico (todo gratuito)

- **Python 3.11+**
- `groq` — generación de guion (LLM principal, ver decisión en §8) 🆕
- `faster-whisper` — transcripción/subtítulos locales
- `moviepy` — edición/ensamblado de video
- `requests` — llamadas a Pexels/Pixabay API
- `pyyaml` — configuración
- `tenacity` — reintentos con backoff exponencial para llamadas a APIs externas (Groq, Pexels/Pixabay) 🆕
- `watchdog` — monitoreo de `input_audio/` para el disparo automático opcional 🆕
- `google-api-python-client` — (fase 2) publicación en YouTube
- `facebook-sdk` o llamadas directas a Graph API — (fase 2) publicación en Facebook

## 6. Fases de implementación

### Fase 1 — MVP local (sin publicación automática) — ✅ implementada
1. `01_generate_script.py`: acepta un tema/idea opcional (`--idea`) o usa la rotación entre los 4 nichos; genera 3 guiones candidatos con Groq, calcula la duración estimada de cada uno y descarta/marca los que no entran en 60-90s, deja elegir uno, y lo guarda en `output/guion_del_dia.txt`. Registra la elección en `history/historial_guiones.json` para no repetir subtemas recientes. 🆕
2. **Pausa manual**: el usuario graba su voz leyendo el guion y guarda el audio en `input_audio/` (o deja corriendo `watch_audio.py` para que el siguiente paso se dispare solo). 🆕
3. `02_finalizar.py`: detecta el audio más reciente, transcribe con Whisper (subtítulos con timestamps, `02_transcribe.py`), busca 3-5 clips/imágenes relevantes según las palabras clave que ya generó Groq en el paso 1 (`03_fetch_broll.py`), y ensambla todo en un video vertical con subtítulos incrustados (`04_assemble_video.py`, MoviePy 2.x — los subtítulos se renderizan con `TextClip`, que en esta versión de MoviePy usa Pillow por dentro y **no requiere tener ImageMagick instalado**). Cada llamada externa (Groq si hace falta reintentar, Pexels/Pixabay) usa reintentos con backoff, y cada corrida queda registrada en `logs/`. 🆕
4. Salida a carpeta `output_videos/` para revisión manual antes de subir. La ruta del video final y la fecha quedan registradas de vuelta en `history/historial_guiones.json`, junto al guion que le dio origen. 🆕

Código: `scripts/01_generate_script.py` … `scripts/04_assemble_video.py`, `scripts/watch_audio.py`, `common/`. Probado end-to-end con audio/imágenes sintéticos y las APIs externas mockeadas (sin gastar cuota real de Groq/Pexels).

### Fase 2 — Publicación semi-automática
1. Integración con YouTube Data API para subir video + título + descripción + tags generados.
2. Integración con Facebook Graph API para publicar el Reel.
3. Mantener revisión manual como paso previo (no publicar sin aprobación) hasta tener confianza en el flujo.

### Fase 3 — Optimización
1. Generación automática de miniaturas.
2. A/B testing de títulos.
3. Analítica básica de rendimiento por nicho, alimentada por el mismo `history/historial_guiones.json` (agregar campo de métricas una vez publicado), para ajustar la rotación de temas. 🆕
4. Subtítulos animados palabra por palabra (karaoke-style) — se deja fuera del MVP a propósito, ver §8. 🆕

## 7. Notas sobre políticas de monetización (contexto para el diseño)

- YouTube no penaliza el uso de IA en sí, sino el contenido "inauténtico": plantillas idénticas sin variación ni aporte humano.
- Usar voz propia + guion con criterio editorial propio + variedad de formato entre videos ayuda a mantenerse dentro de política.
- Requisitos actuales para monetización: 1,000 suscriptores + 4,000 horas de vista en 12 meses, o 10M vistas en Shorts en 90 días (sujeto a cambios).
- Si en algún punto se usa voz sintética o imágenes/video realista generado por IA, activar el disclosure "contenido alterado o sintético" al subir.

## 8. Decisiones (antes eran preguntas abiertas) 🆕

Estas eran las preguntas abiertas de la v1; quedan resueltas así para poder avanzar con la implementación:

- **¿Qué LLM gratuito usar?** → **Groq (Llama)** como proveedor principal: tier gratuito generoso, latencia muy baja (importante porque ahora se generan 3 candidatos por ejecución en vez de 1). Requiere una API key gratuita de Groq en `config/settings.yaml`. Si en el futuro Groq se vuelve inestable o cambia sus límites, el wrapper en `common/llm_client.py` está pensado para poder agregar Gemini como fallback sin tocar el resto del pipeline — no se implementa en el MVP, se deja como gancho.
- **¿Rotación fija o por tendencias?** → Rotación fija por defecto (como en la v1), pero ahora el usuario puede sobreescribirla puntualmente con `--idea "..."` cuando tenga un tema específico en mente. Selección por tendencias/calendario queda para una fase posterior si hace falta.
- **¿Nivel de personalización de subtítulos en la v1?** → Estilo simple y fijo (texto grande, contorno para legibilidad, sin animación palabra por palabra) para no complicar el MVP. La animación tipo "karaoke" (resaltar palabra por palabra) se deja explícitamente para la Fase 3, una vez que el flujo base esté validado.

## 9. Resumen de mejoras aplicadas en esta revisión 🆕

1. **Guion con idea propia + selección entre opciones**: en vez de recibir un único guion generado automáticamente, el usuario puede dar un tema (`--idea`) y elige entre varios candidatos que genera el LLM, en la misma ejecución de `01_generate_script.py` (no rompe el flujo de dos comandos).
2. **Validación de duración antes de grabar**: cada candidato de guion muestra su duración estimada (según palabras-por-minuto configurables) para evitar grabar un guion que termine siendo muy corto o muy largo para el formato 60-90s.
3. **Manejo de errores y logging**: todas las llamadas a APIs externas (Groq, Pexels/Pixabay) usan reintentos con backoff exponencial (`tenacity`), y cada ejecución deja un log con timestamp en `logs/` para poder diagnosticar fallos sin tener que reproducirlos a ciegas.
4. **Watcher automático opcional**: `watch_audio.py` puede correr en segundo plano y disparar `02_finalizar.py` automáticamente en cuanto detecta un audio nuevo en `input_audio/`, adelantando a la Fase 1 algo que la v1 dejaba para más adelante.
5. **Historial de guiones/temas**: `history/historial_guiones.json` registra qué subtemas ya se usaron por nicho y cuándo, para evitar repetir contenido y para tener datos ya listos cuando llegue la analítica de la Fase 3.

## 10. Configuración sugerida (`config/settings.yaml`) 🆕

Ejemplo orientativo de las claves que el resto del documento asume; se termina de ajustar durante la implementación:

```yaml
llm:
  provider: groq
  groq_api_key: "TU_API_KEY_AQUI"
  modelo: "openai/gpt-oss-20b"
  candidatos_por_ejecucion: 3
  max_reintentos: 3

guion:
  palabras_por_minuto: 150       # para estimar duración de narración
  duracion_objetivo_seg: [60, 90]
  nichos: [tecnologia, programacion, videojuegos, peliculas]

broll:
  proveedor: pexels              # pexels | pixabay
  api_key: "TU_API_KEY_AQUI"
  clips_por_video: [3, 5]

video:
  formato: vertical               # 1080x1920
  subtitulos_estilo: simple        # simple | karaoke (fase 3)

historial:
  ruta: "history/historial_guiones.json"
  evitar_repetir_dias: 14

logging:
  ruta: "logs/"
  nivel: INFO
```

## 11. Acceso remoto — webapp (v3) 🆕

Los scripts de CLI (`01_generate_script.py`, `02_finalizar.py`) siguen existiendo igual y siguen andando en tu compu. Además, `webapp/` expone la misma lógica como una API + página web mínima, para poder usar el pipeline desde cualquier lugar sin depender de que tu compu esté prendida:

1. Abrís la página, pegás un token de acceso (candado simple, ver más abajo).
2. Pedís un guion (con o sin idea puntual) → el LLM te da varios candidatos.
3. Elegís uno → te muestra el texto para que lo grabes con lo que tengas a mano (celu, Audacity, etc.).
4. Subís el archivo de audio grabado → se procesa en background (Whisper + B-roll + MoviePy), un audio a la vez para no quedarse sin RAM.
5. Cuando termina, descargás el video final.

**No hay una segunda implementación del pipeline**: `webapp/main.py` reusa exactamente los mismos módulos de `common/` y los mismos scripts numerados (`02_transcribe.py`, `03_fetch_broll.py`, `04_assemble_video.py`) que ya usa la CLI.

### Por qué no un PaaS con tier gratis (Render/Railway/etc.)

Whisper y MoviePy necesitan RAM y CPU sostenida por varios minutos. Los tiers gratuitos típicos tienen RAM chica, cortan requests largos, y borran el disco en cada redeploy — alto riesgo de que el video se corte a mitad de proceso. En cambio, una **VM siempre gratis** (recomendado: Oracle Cloud Free Tier, hasta 4 OCPU ARM + 24GB RAM sin costo) no tiene esos límites. La app queda en Docker, así que si más adelante conviene otro hosting, se mueve sin reescribir nada — ver `docs/deploy-oracle-cloud-free-tier.md` para el paso a paso.

### Seguridad

La webapp queda expuesta a internet, así que todos los endpoints requieren un header `X-Api-Token` que coincida con la variable de entorno `WEBAPP_TOKEN` (candado simple, no es un sistema de usuarios — alcanza para que no cualquiera gaste tu cuota de Groq/Pexels). El despliegue recomendado incluye Caddy como reverse proxy con HTTPS automático (Let's Encrypt), así el token nunca viaja en texto plano por la red.

### Limitaciones conocidas (a mejorar en una iteración futura)

- El estado de los trabajos en curso vive en memoria: un reinicio del contenedor a mitad de un procesamiento pierde ese trabajo puntual (el audio se puede volver a subir).
- Los guiones candidatos generados y no elegidos se descartan solos después de 1 hora.
- Un solo usuario/token para toda la instancia — para un equipo con varias personas grabando, habría que sumar un sistema de usuarios real.
