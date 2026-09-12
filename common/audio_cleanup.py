"""Limpieza de audio (reducción de ruido + normalización) vía ffmpeg.

Se corre sobre el audio grabado por el usuario ANTES de transcribir y de
usarlo en el video final, así la mejora se refleja en las dos etapas: mejor
insumo para Whisper, y mejor sonido en el video (voz más pareja, sin el
volumen "como se grabó" del micrófono del celu).

Usa el binario de ffmpeg que ya trae `imageio-ffmpeg` (dependencia de
MoviePy) en vez de depender de que haya un ffmpeg del sistema en el PATH —
funciona igual en Docker, en Render, o en una instalación local con
`pip install`.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import imageio_ffmpeg

from common.logging_config import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)

# highpass: saca ronroneo/graves de fondo (aire acondicionado, manejo del
#   micrófono) sin tocar el rango de la voz humana.
# afftdn: reducción de ruido de fondo (ventilador, hiss del micrófono) por FFT.
# loudnorm: normalización de volumen a -16 LUFS, el estándar de facto para
#   audio de streaming/redes — evita que la narración quede más floja o más
#   fuerte que el resto según cómo haya grabado cada uno.
FILTRO_LIMPIEZA = "highpass=f=80,afftdn=nf=-25,loudnorm=I=-16:TP=-1.5:LRA=11"


def limpiar_audio(entrada: str | Path, salida: str | Path) -> Path:
    """Aplica denoise + normalización. Si ffmpeg falla, devuelve el audio original sin tocar."""
    entrada = Path(entrada)
    salida = Path(salida)
    salida.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    comando = [
        ffmpeg, "-y", "-i", str(entrada),
        "-af", FILTRO_LIMPIEZA,
        "-ar", "44100",
        str(salida),
    ]
    logger.info("Limpiando audio (denoise + normalización) de %s...", entrada)
    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        logger.warning(
            "No se pudo limpiar el audio, se usa el original sin procesar. "
            "ffmpeg dijo: %s",
            resultado.stderr[-500:].strip(),
        )
        return entrada

    logger.info("Audio limpio guardado en %s.", salida)
    return salida
