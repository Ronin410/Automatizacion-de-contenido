#!/usr/bin/env python3
"""Orquesta la etapa final del pipeline: transcribe, busca B-roll y ensambla el video.

Uso (después de grabar tu narración y guardarla en input_audio/):

    python scripts/02_finalizar.py

Detecta automáticamente el audio más reciente en `input_audio/`. Cada etapa
(Whisper, Pexels/Pixabay, MoviePy) ya maneja sus propios reintentos; si una
etapa falla después de reintentar, el script se detiene con un mensaje claro
en vez de dejar un video a medio ensamblar en output_videos/.
"""
from __future__ import annotations

import importlib
import random
import sys
from datetime import datetime
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from common.history import actualizar_ultima_entrada, ultima_entrada  # noqa: E402
from common.logging_config import setup_logging  # noqa: E402

# Los módulos de las otras etapas empiezan con un número, así que no son
# importables con `import 02_transcribe` (no es un identificador válido);
# se cargan por nombre de archivo con importlib, igual que en las pruebas.
transcribe_mod = importlib.import_module("02_transcribe")
broll_mod = importlib.import_module("03_fetch_broll")
assemble_mod = importlib.import_module("04_assemble_video")

AUDIO_EXTENSIONES = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}


def cargar_config(ruta: Path) -> dict:
    if not ruta.exists():
        ejemplo = ruta.parent / "settings.example.yaml"
        raise FileNotFoundError(
            f"No existe {ruta}. Copiá {ejemplo.name} a {ruta.name} y completá tus API keys."
        )
    with ruta.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def audio_mas_reciente(carpeta: Path) -> Path:
    candidatos = [p for p in carpeta.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONES]
    if not candidatos:
        raise FileNotFoundError(
            f"No hay ningún audio ({', '.join(sorted(AUDIO_EXTENSIONES))}) en {carpeta}. "
            "Grabá tu narración y guardala ahí antes de correr este script."
        )
    return max(candidatos, key=lambda p: p.stat().st_mtime)


def keywords_del_guion_actual(historial_ruta: Path) -> list[str]:
    """Reusa las palabras clave que ya generó el LLM en 01_generate_script.py."""
    entrada = ultima_entrada(historial_ruta)
    if entrada and entrada.get("palabras_clave"):
        return list(entrada["palabras_clave"])
    return []


def main() -> int:
    config = cargar_config(BASE_DIR / "config" / "settings.yaml")
    logging_cfg = config.get("logging", {}) or {}
    logger = setup_logging(
        log_dir=BASE_DIR / logging_cfg.get("ruta", "logs"),
        nivel=logging_cfg.get("nivel", "INFO"),
    )

    whisper_cfg = config.get("whisper", {}) or {}
    broll_cfg = config.get("broll", {}) or {}
    video_cfg = config.get("video", {}) or {}
    historial_cfg = config.get("historial", {}) or {}
    historial_ruta = BASE_DIR / historial_cfg.get("ruta", "history/historial_guiones.json")

    try:
        audio_path = audio_mas_reciente(BASE_DIR / "input_audio")
    except FileNotFoundError as exc:
        logger.error(str(exc))
        print(f"\n{exc}")
        return 1
    logger.info("Usando audio más reciente: %s", audio_path)

    # --- 1) Transcripción / subtítulos -------------------------------------------------
    try:
        subtitulos = transcribe_mod.transcribir_audio(
            audio_path,
            modelo=whisper_cfg.get("modelo", "small"),
            idioma=whisper_cfg.get("idioma", "es"),
            device=whisper_cfg.get("device", "cpu"),
            compute_type=whisper_cfg.get("compute_type", "int8"),
        )
    except Exception as exc:  # noqa: BLE001 - error real de Whisper, se informa y se corta
        logger.error("Falló la transcripción con Whisper: %s", exc)
        print(f"\nNo se pudo transcribir el audio: {exc}")
        return 1

    transcribe_mod.guardar_srt(subtitulos, BASE_DIR / "output" / "subtitulos.srt")

    # --- 2) B-roll -----------------------------------------------------------------------
    keywords = keywords_del_guion_actual(historial_ruta)
    if not keywords:
        logger.warning("No hay palabras clave guardadas en el historial; se busca B-roll genérico.")
    cantidad_min, cantidad_max = broll_cfg.get("clips_por_video", [3, 5])
    cantidad = random.randint(int(cantidad_min), int(cantidad_max))

    try:
        cliente_broll = broll_mod.BrollClient(
            proveedor=broll_cfg.get("proveedor", "pexels"),
            api_key=broll_cfg.get("api_key"),
            max_reintentos=broll_cfg.get("max_reintentos", 3),
        )
        broll_clips = cliente_broll.buscar_y_descargar(
            keywords, cantidad, BASE_DIR / "assets" / "broll_temp"
        )
    except (broll_mod.BrollError, RuntimeError) as exc:
        logger.error("Falló la búsqueda de B-roll: %s", exc)
        print(f"\nNo se pudo conseguir B-roll: {exc}")
        return 1

    # --- 3) Ensamblado ---------------------------------------------------------------------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    salida = BASE_DIR / "output_videos" / f"reel_{timestamp}.mp4"
    try:
        assemble_mod.ensamblar_video(audio_path, subtitulos, broll_clips, salida, video_cfg)
    except Exception as exc:  # noqa: BLE001 - error real de MoviePy/ffmpeg, se informa y se corta
        logger.error("Falló el ensamblado del video: %s", exc)
        print(f"\nNo se pudo ensamblar el video: {exc}")
        return 1

    actualizar_ultima_entrada(
        historial_ruta,
        {"video_path": str(salida), "fecha_finalizado": datetime.now().isoformat(timespec="seconds")},
    )

    logger.info("Listo: %s", salida)
    print(f"\nVideo listo para revisión en: {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
