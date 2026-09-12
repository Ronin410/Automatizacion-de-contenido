"""Música de fondo opcional para el video final.

No viene con pistas incluidas (son archivos de audio con su propia licencia,
no algo que este proyecto pueda decidir por vos) — el usuario deja sus
propios archivos royalty-free en `assets/musica/` y acá se elige uno al azar
para cada video. Si la carpeta está vacía, simplemente no se agrega música
(no es un error).
"""
from __future__ import annotations

import logging
import random
from pathlib import Path

from common.logging_config import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)

EXTENSIONES_AUDIO = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}


def elegir_pista(base_dir: Path) -> Path | None:
    carpeta = base_dir / "assets" / "musica"
    if not carpeta.exists():
        return None
    pistas = [p for p in carpeta.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONES_AUDIO]
    if not pistas:
        return None
    elegida = random.choice(pistas)
    logger.info("Música de fondo elegida: %s", elegida.name)
    return elegida
