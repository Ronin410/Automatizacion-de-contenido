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
from webapp.auth import verificar_token  # noqa: E402
from webapp.jobs import GestorTrabajos  # noqa: E402

# Los módulos de estas etapas empiezan con un número (no son importables con
# `import 02_transcribe`), así que se cargan por nombre de archivo, igual
# que ya hace scripts/02_finalizar.py.
transcribe_mod = importlib.import_module("02_transcribe")
broll_mod = importlib.import_module("03_fetch_broll")
assemble_mod = importlib.import_module("04_assemble_video")

CONFIG_PATH = BASE_DIR / "config" / "settings.yaml"
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
    historial_ruta = BASE_DIR / (config.get("historial", {}) or {}).get(
        "ruta", "history/historial_guiones.json"
    )

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

    cantidad_min, cantidad_max = broll_cfg.get("clips_por_video", [3, 5])
    cantidad = random.randint(int(cantidad_min), int(cantidad_max))
    cliente_broll = broll_mod.BrollClient(
        proveedor=broll_cfg.get("proveedor", "pexels"),
        api_key=broll_cfg.get("api_key"),
        max_reintentos=broll_cfg.get("max_reintentos", 3),
    )
    broll_clips = cliente_broll.buscar_y_descargar(keywords, cantidad, BASE_DIR / "assets" / "broll_temp")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    salida = BASE_DIR / "output_videos" / f"reel_{timestamp}.mp4"
    assemble_mod.ensamblar_video(audio_path, subtitulos, broll_clips, salida, video_cfg)

    actualizar_ultima_entrada(
        historial_ruta,
        {"video_path": str(salida), "fecha_finalizado": datetime.now().isoformat(timespec="seconds")},
    )
    return salida


gestor = GestorTrabajos(procesar_audio=_procesar_audio)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


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
    if nicho and nicho not in nichos:
        raise HTTPException(400, f"Nicho inválido: {nicho!r} (opciones: {nichos}).")

    nicho_final = nicho or elegir_nicho_por_rotacion(nichos, historial_ruta)
    evitar = temas_recientes(historial_ruta, nicho_final, dias=evitar_dias)
    palabras_por_minuto = guion_cfg.get("palabras_por_minuto", 150)
    minimo, maximo = (float(v) for v in guion_cfg.get("duracion_objetivo_seg", [60, 90]))

    try:
        cliente = GroqScriptClient(
            api_key=llm_cfg.get("groq_api_key"),
            modelo=llm_cfg.get("modelo", "llama-3.1-8b-instant"),
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


@app.get("/api/procesos/{job_id}", dependencies=[Depends(verificar_token)])
def estado_proceso(job_id: str) -> dict:
    trabajo = gestor.estado(job_id)
    if trabajo is None:
        raise HTTPException(404, "No existe ese job_id (¿el servidor se reinició desde que lo creaste?).")
    return trabajo.to_dict()


@app.get("/api/videos/{job_id}", dependencies=[Depends(verificar_token)])
def descargar_video(job_id: str) -> FileResponse:
    trabajo = gestor.estado(job_id)
    if trabajo is None:
        raise HTTPException(404, "No existe ese job_id.")
    if trabajo.estado != "listo" or not trabajo.video_path:
        raise HTTPException(409, f"El video todavía no está listo (estado actual: {trabajo.estado}).")
    return FileResponse(trabajo.video_path, media_type="video/mp4", filename=Path(trabajo.video_path).name)
