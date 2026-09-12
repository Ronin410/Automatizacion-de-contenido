#!/usr/bin/env python3
"""Transcripción y subtítulos locales con faster-whisper (CPU, sin costo).

Se usa como módulo desde 02_finalizar.py, pero también se puede correr solo
para probar la transcripción de un audio puntual:

    python scripts/02_transcribe.py input_audio/mi_narracion.wav
"""
from __future__ import annotations

import gc
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from faster_whisper import WhisperModel

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from common.logging_config import LOGGER_NAME  # noqa: E402

logger = logging.getLogger(LOGGER_NAME)


@dataclass
class Subtitulo:
    inicio: float
    fin: float
    texto: str


def transcribir_audio(
    audio_path: str | Path,
    modelo: str = "small",
    idioma: str = "es",
    device: str = "cpu",
    compute_type: str = "int8",
) -> list[Subtitulo]:
    """Transcribe un audio y devuelve la lista de subtítulos con timestamps.

    La primera vez que se usa un `modelo` dado, faster-whisper lo descarga
    de Hugging Face y lo cachea localmente; corridas siguientes son offline.
    """
    logger.info("Cargando modelo Whisper '%s' (device=%s, compute_type=%s)...", modelo, device, compute_type)
    model = WhisperModel(modelo, device=device, compute_type=compute_type)

    logger.info("Transcribiendo %s...", audio_path)
    segmentos, info = model.transcribe(str(audio_path), language=idioma, vad_filter=True)
    subtitulos = [
        Subtitulo(inicio=s.start, fin=s.end, texto=s.text.strip())
        for s in segmentos
        if s.text.strip()
    ]

    # Liberar el modelo apenas termina, antes de pasar a B-roll/MoviePy: en hosts
    # con poca RAM (ej. el tier gratis de Render, 512MB) sumar las dos etapas sin
    # soltar esto primero es lo que termina tirando un OOM a mitad de proceso.
    del model
    gc.collect()

    if not subtitulos:
        raise RuntimeError(
            "Whisper no devolvió ningún segmento de texto. Revisá que el audio no esté "
            "vacío, silencioso, o en un formato que no se pudo leer."
        )

    logger.info(
        "Transcripción lista: %d segmentos, duración detectada %.1fs (idioma=%s, prob=%.2f).",
        len(subtitulos), info.duration, info.language, info.language_probability,
    )
    return subtitulos


def guardar_srt(subtitulos: list[Subtitulo], ruta: str | Path) -> None:
    """Guarda los subtítulos en formato .srt (útil para depurar o revisar a mano)."""

    def _formato_tiempo(seg: float) -> str:
        horas, resto = divmod(max(seg, 0.0), 3600)
        minutos, resto = divmod(resto, 60)
        segundos, ms = divmod(resto, 1)
        return f"{int(horas):02d}:{int(minutos):02d}:{int(segundos):02d},{int(ms * 1000):03d}"

    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as f:
        for i, sub in enumerate(subtitulos, start=1):
            f.write(f"{i}\n{_formato_tiempo(sub.inicio)} --> {_formato_tiempo(sub.fin)}\n{sub.texto}\n\n")
    logger.info("Subtítulos guardados en %s", ruta)


def _main_cli() -> int:
    if len(sys.argv) < 2:
        print("Uso: python scripts/02_transcribe.py <ruta_audio> [modelo]")
        return 1
    audio_path = sys.argv[1]
    modelo = sys.argv[2] if len(sys.argv) > 2 else "small"

    from common.logging_config import setup_logging

    setup_logging(log_dir=BASE_DIR / "logs")
    subtitulos = transcribir_audio(audio_path, modelo=modelo)
    for sub in subtitulos:
        print(f"[{sub.inicio:6.1f}s - {sub.fin:6.1f}s] {sub.texto}")
    guardar_srt(subtitulos, BASE_DIR / "output" / "subtitulos.srt")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main_cli())
