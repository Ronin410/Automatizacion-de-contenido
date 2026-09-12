"""API + página web mínima para correr el pipeline sin depender de tu compu.

Pantallas (servidas en `/`, ver `webapp/static/index.html`):
    1. Pedís un guion (idea opcional) → el LLM te da varios candidatos.
    2. Elegís uno → te lo muestra para que lo grabes con el celu/micrófono.
    3. Subís el archivo de audio grabado → se procesa en background
       (Whisper + B-roll + MoviePy) y podés seguir el estado.
    4. Cuando está listo, descargás el video final.

Todo esto reusa exactamente la misma lógica de `common/` y de los scripts
numerados (`02_transcribe.py`, `03_fetch_broll.py`, `04_assemble_video.py`)
que ya se usan desde la línea de comandos — no hay una segunda
implementación del pipeline, solo una capa de API arriba.
"""
from __future__ import annotations

import importlib
import logging
import os
import random
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from common.config import cargar_config  # noqa: E402
from common.guion import NICHOS_DEFAULT, elegir_nicho_por_rotacion, estimar_duracion_seg  # noqa: E402
from common.history import actualizar_ultima_entrada, registrar_guion, temas_recientes, ultima_entrada  # noqa: E402
from common.llm_client import GroqScriptClient, LLMResponseError  # noqa: E402
from common.logging_config import setup_logging  # noqa: E402
import common.audio_cleanup as audio_cleanup  # noqa: E402
import common.media_usuario as media_usuario  # noqa: E402
import common.musica as musica_mod  # noqa: E402
import common.overlays as overlays_mod  # noqa: E402
from webapp.auth import verificar_token  # noqa: E402
from webapp.jobs import GestorTrabajos  # noqa: E402

# Los módulos de estas etapas empiezan con un número (no son importables con
# `import 02_transcribe`), así que se cargan por nombre de archivo, igual
# que ya hace scripts/02_finalizar.py.
transcribe_mod = importlib.import_module("02_transcribe")
broll_mod = importlib.import_module("03_fetch_broll")
assemble_mod = importlib.import_module("04_assemble_video")

# Localmente/Docker-compose: config/settings.yaml de siempre. En Render (y
# PaaS similares) los "Secret Files" no admiten subcarpetas en el nombre y
# quedan en /etc/secrets/<archivo> — ahí seteamos CONFIG_PATH a esa ruta.
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", str(BASE_DIR / "config" / "settings.yaml")))
TTL_CANDIDATOS_PENDIENTES_SEG = 3600  # 1h: si generás y no elegís, se descarta

logger = setup_logging(log_dir=BASE_DIR / "logs")
app = FastAPI(title="Pipeline de Reels")

# Candidatos ya generados, esperando que el usuario elija uno. En memoria:
# alcanza para un solo usuario y evita depender de un disco/DB extra.
_candidatos_pendientes: dict[str, dict] = {}


def _config() -> dict:
    return cargar_config(CONFIG_PATH)


def _limpiar_pendientes_viejos() -> None:
    limite = time.time() - TTL_CANDIDATOS_PENDIENTES_SEG
    vencidos = [gid for gid, datos in _candidatos_pendientes.items() if datos["creado"] < limite]
    for gid in vencidos:
        _candidatos_pendientes.pop(gid, None)


def _procesar_audio(audio_path: Path) -> Path:
    """Whisper + B-roll + ensamblado para un audio ya subido (misma lógica que 02_finalizar.py)."""
    config = _config()
    whisper_cfg = config.get("whisper", {}) or {}
    broll_cfg = config.get("broll", {}) or {}
    video_cfg = config.get("video", {}) or {}
    audio_cfg = config.get("audio", {}) or {}
    musica_cfg = config.get("musica", {}) or {}
    historial_ruta = BASE_DIR / (config.get("historial", {}) or {}).get(
        "ruta", "history/historial_guiones.json"
    )

    # Denoise + normalización antes que nada: mejora tanto la transcripción
    # como el audio del video final. Si ffmpeg falla, sigue con el original.
    if audio_cfg.get("limpiar", True):
        audio_path = audio_cleanup.limpiar_audio(audio_path, BASE_DIR / "output" / "audio_limpio.wav")

    subtitulos = transcribe_mod.transcribir_audio(
        audio_path,
        modelo=whisper_cfg.get("modelo", "small"),
        idioma=whisper_cfg.get("idioma", "es"),
        device=whisper_cfg.get("device", "cpu"),
        compute_type=whisper_cfg.get("compute_type", "int8"),
    )
    transcribe_mod.guardar_srt(subtitulos, BASE_DIR / "output" / "subtitulos.srt")

    entrada = ultima_entrada(historial_ruta)
    keywords = list(entrada["palabras_clave"]) if entrada and entrada.get("palabras_clave") else []

    # Media propia primero (si subieron fotos/videos, van sí o sí); el resto de los
    # clips, hasta completar la cantidad configurada, se busca automático en Pexels/Pixabay.
    clips_usuario = media_usuario.tomar_pendientes_como_clips(BASE_DIR)
    cantidad_min, cantidad_max = broll_cfg.get("clips_por_video", [3, 5])
    cantidad_total = random.randint(int(cantidad_min), int(cantidad_max))
    cantidad_auto = max(0, cantidad_total - len(clips_usuario))

    broll_auto = []
    if cantidad_auto > 0:
        cliente_broll = broll_mod.BrollClient(
            proveedor=broll_cfg.get("proveedor", "pexels"),
            api_key=broll_cfg.get("api_key"),
            max_reintentos=broll_cfg.get("max_reintentos", 3),
        )
        broll_auto = cliente_broll.buscar_y_descargar(keywords, cantidad_auto, BASE_DIR / "assets" / "broll_temp")

    broll_clips = clips_usuario + broll_auto
    overlays_pendientes = overlays_mod.tomar_pendientes(BASE_DIR)
    musica_path = musica_mod.elegir_pista(BASE_DIR) if musica_cfg.get("activar", True) else None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    salida = BASE_DIR / "output_videos" / f"reel_{timestamp}.mp4"
    assemble_mod.ensamblar_video(
        audio_path, subtitulos, broll_clips, salida, video_cfg,
        overlays=overlays_pendientes,
        musica_path=musica_path,
        musica_volumen=musica_cfg.get("volumen", 0.15),
    )

    actualizar_ultima_entrada(
        historial_ruta,
        {"video_path": str(salida), "fecha_finalizado": datetime.now().isoformat(timespec="seconds")},
    )
    return salida


gestor = GestorTrabajos(procesar_audio=_procesar_audio, estado_path=BASE_DIR / "logs" / "jobs_estado.json")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/nichos", dependencies=[Depends(verificar_token)])
def listar_nichos() -> dict:
    """Nichos configurados (solo como sugerencia: el campo de nicho acepta texto libre)."""
    config = _config()
    nichos = (config.get("guion", {}) or {}).get("nichos") or NICHOS_DEFAULT
    return {"nichos": nichos}


@app.post("/api/guiones/generar", dependencies=[Depends(verificar_token)])
def generar_guiones(idea: str | None = Form(None), nicho: str | None = Form(None)) -> dict:
    _limpiar_pendientes_viejos()
    config = _config()
    guion_cfg = config.get("guion", {}) or {}
    llm_cfg = config.get("llm", {}) or {}
    historial_ruta = BASE_DIR / (config.get("historial", {}) or {}).get(
        "ruta", "history/historial_guiones.json"
    )
    evitar_dias = (config.get("historial", {}) or {}).get("evitar_repetir_dias", 14)

    nichos = guion_cfg.get("nichos") or NICHOS_DEFAULT
    # Texto libre a propósito: no hace falta que esté en `nichos` (esa lista
    # es solo para la rotación automática cuando no se especifica ninguno).
    nicho = (nicho or "").strip() or None
    nicho_final = nicho or elegir_nicho_por_rotacion(nichos, historial_ruta)
    evitar = temas_recientes(historial_ruta, nicho_final, dias=evitar_dias)
    palabras_por_minuto = guion_cfg.get("palabras_por_minuto", 150)
    minimo, maximo = (float(v) for v in guion_cfg.get("duracion_objetivo_seg", [60, 90]))

    try:
        cliente = GroqScriptClient(
            api_key=llm_cfg.get("groq_api_key"),
            modelo=llm_cfg.get("modelo", "openai/gpt-oss-20b"),
            max_reintentos=llm_cfg.get("max_reintentos", 3),
        )
        candidatos = cliente.generar_candidatos(
            nicho_final, idea, llm_cfg.get("candidatos_por_ejecucion", 3), evitar
        )
    except (RuntimeError, LLMResponseError) as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - falla de red/API de Groq ya reintentada
        raise HTTPException(502, f"Falló la API de Groq: {exc}") from exc

    generado_id = uuid.uuid4().hex[:12]
    _candidatos_pendientes[generado_id] = {
        "nicho": nicho_final,
        "idea": idea,
        "candidatos": candidatos,
        "creado": time.time(),
    }

    candidatos_resp = []
    for i, c in enumerate(candidatos):
        duracion = estimar_duracion_seg(c.guion, palabras_por_minuto)
        candidatos_resp.append(
            {
                "indice": i,
                "titulo": c.titulo,
                "guion": c.guion,
                "palabras_clave": c.palabras_clave,
                "duracion_estimada_seg": duracion,
                "dentro_de_rango": minimo <= duracion <= maximo,
            }
        )

    return {
        "generado_id": generado_id,
        "nicho": nicho_final,
        "rango_objetivo_seg": [minimo, maximo],
        "candidatos": candidatos_resp,
    }


@app.post("/api/guiones/elegir", dependencies=[Depends(verificar_token)])
def elegir_guion(generado_id: str = Form(...), indice: int = Form(...)) -> dict:
    pendiente = _candidatos_pendientes.pop(generado_id, None)
    if pendiente is None:
        raise HTTPException(
            404, "No hay candidatos pendientes con ese generado_id (¿ya expiró o ya elegiste uno?)."
        )
    candidatos = pendiente["candidatos"]
    if not (0 <= indice < len(candidatos)):
        raise HTTPException(400, f"Índice fuera de rango (0-{len(candidatos) - 1}).")
    elegido = candidatos[indice]

    config = _config()
    historial_ruta = BASE_DIR / (config.get("historial", {}) or {}).get(
        "ruta", "history/historial_guiones.json"
    )
    palabras_por_minuto = (config.get("guion", {}) or {}).get("palabras_por_minuto", 150)

    output_dir = BASE_DIR / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "guion_del_dia.txt").write_text(elegido.guion + "\n", encoding="utf-8")

    duracion = estimar_duracion_seg(elegido.guion, palabras_por_minuto)
    registrar_guion(
        historial_ruta,
        {
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "nicho": pendiente["nicho"],
            "idea": pendiente["idea"],
            "titulo": elegido.titulo,
            "duracion_estimada_seg": duracion,
            "palabras_clave": elegido.palabras_clave,
        },
    )
    logger.info("Guion elegido vía webapp: '%s' (nicho=%s).", elegido.titulo, pendiente["nicho"])
    return {"titulo": elegido.titulo, "guion": elegido.guion, "duracion_estimada_seg": duracion}


@app.get("/api/guiones/actual", dependencies=[Depends(verificar_token)])
def guion_actual() -> dict:
    """Guion elegido más reciente que todavía no tiene un video generado.

    Sirve para que la página recupere el estado si refrescás o volvés más
    tarde (por ejemplo, elegiste un guion pero todavía no grabaste el
    audio): sin esto, ese guion "pendiente de grabar" solo vivía en el
    estado de React/JS del navegador y se perdía al refrescar.
    """
    config = _config()
    historial_ruta = BASE_DIR / (config.get("historial", {}) or {}).get(
        "ruta", "history/historial_guiones.json"
    )
    entrada = ultima_entrada(historial_ruta)
    if not entrada or entrada.get("video_path"):
        return {"pendiente": False}

    guion_path = BASE_DIR / "output" / "guion_del_dia.txt"
    if not guion_path.exists():
        return {"pendiente": False}

    return {
        "pendiente": True,
        "titulo": entrada.get("titulo", ""),
        "guion": guion_path.read_text(encoding="utf-8").strip(),
        "duracion_estimada_seg": entrada.get("duracion_estimada_seg"),
    }


@app.get("/api/media/pendiente", dependencies=[Depends(verificar_token)])
def media_pendiente() -> dict:
    """Fotos/videos propios ya subidos, esperando a que se arme el próximo video."""
    return {"archivos": media_usuario.listar_pendientes(BASE_DIR)}


@app.post("/api/media/subir", dependencies=[Depends(verificar_token)])
async def subir_media(archivo: UploadFile = File(...)) -> dict:
    contenido = await archivo.read()
    try:
        info = media_usuario.agregar_pendiente(BASE_DIR, archivo.filename or "", contenido)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return info


@app.delete("/api/media/pendiente/{nombre}", dependencies=[Depends(verificar_token)])
def eliminar_media_pendiente(nombre: str) -> dict:
    try:
        borrado = media_usuario.eliminar_pendiente(BASE_DIR, nombre)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not borrado:
        raise HTTPException(404, "Ese archivo ya no está en la cola.")
    return {"eliminado": True}


@app.get("/api/overlays/pendiente", dependencies=[Depends(verificar_token)])
def overlays_pendientes() -> dict:
    """Memes/avatar/stickers ya subidos, esperando a que se arme el próximo video."""
    return {"archivos": overlays_mod.listar_pendientes(BASE_DIR)}


@app.post("/api/overlays/subir", dependencies=[Depends(verificar_token)])
async def subir_overlay(archivo: UploadFile = File(...)) -> dict:
    contenido = await archivo.read()
    try:
        info = overlays_mod.agregar_pendiente(BASE_DIR, archivo.filename or "", contenido)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return info


@app.delete("/api/overlays/pendiente/{nombre}", dependencies=[Depends(verificar_token)])
def eliminar_overlay_pendiente(nombre: str) -> dict:
    try:
        borrado = overlays_mod.eliminar_pendiente(BASE_DIR, nombre)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not borrado:
        raise HTTPException(404, "Ese archivo ya no está en la cola.")
    return {"eliminado": True}


AUDIO_EXTENSIONES_PERMITIDAS = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}


@app.post("/api/audio/subir", dependencies=[Depends(verificar_token)])
async def subir_audio(archivo: UploadFile = File(...)) -> dict:
    extension = Path(archivo.filename or "").suffix.lower()
    if extension not in AUDIO_EXTENSIONES_PERMITIDAS:
        raise HTTPException(
            400, f"Extensión no soportada: {extension!r} (usar {sorted(AUDIO_EXTENSIONES_PERMITIDAS)})."
        )

    carpeta = BASE_DIR / "input_audio"
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}{extension}"
    contenido = await archivo.read()
    destino.write_bytes(contenido)
    logger.info("Audio subido vía webapp: %s (%d bytes).", destino, len(contenido))

    job_id = gestor.encolar(destino)
    return {"job_id": job_id}


@app.get("/api/procesos/actual", dependencies=[Depends(verificar_token)])
def proceso_actual() -> dict:
    """Último trabajo encolado (para retomarlo si refrescás la página mientras procesa)."""
    trabajo = gestor.ultimo()
    if trabajo is None:
        return {"existe": False}
    return {"existe": True, **trabajo.to_dict()}


# OJO con el orden: esta ruta con parámetro va DESPUÉS de /api/procesos/actual,
# si no FastAPI la matchea primero y "actual" nunca llega a la de arriba.
@app.get("/api/procesos/{job_id}", dependencies=[Depends(verificar_token)])
def estado_proceso(job_id: str) -> dict:
    trabajo = gestor.estado(job_id)
    if trabajo is None:
        raise HTTPException(
            404,
            "No existe ese job_id. Si el servidor se reinició (común en tiers gratis con poca RAM o "
            "por inactividad) y el disco no es persistente, el registro también se perdió — volvé a "
            "subir el audio.",
        )
    return trabajo.to_dict()


@app.get("/api/videos/{job_id}", dependencies=[Depends(verificar_token)])
def descargar_video(job_id: str) -> FileResponse:
    trabajo = gestor.estado(job_id)
    if trabajo is None:
        raise HTTPException(404, "No existe ese job_id.")
    if trabajo.estado != "listo" or not trabajo.video_path:
        raise HTTPException(409, f"El video todavía no está listo (estado actual: {trabajo.estado}).")
    return FileResponse(trabajo.video_path, media_type="video/mp4", filename=Path(trabajo.video_path).name)
