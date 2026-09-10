"""Configuración centralizada de logging para los scripts del pipeline.

Cada script (01_generate_script.py, 02_finalizar.py, etc.) llama a
`setup_logging()` una sola vez al arrancar. Deja un log con timestamp por
corrida en `logs/` además de imprimir en consola, para poder diagnosticar
fallos de las APIs externas (Groq, Pexels/Pixabay, Whisper) sin tener que
reproducirlos a ciegas.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

LOGGER_NAME = "content_pipeline"


def setup_logging(log_dir: str | Path = "logs", nivel: str = "INFO") -> logging.Logger:
    """Configura y devuelve el logger compartido del pipeline.

    Idempotente: si se llama más de una vez en el mismo proceso, no duplica
    handlers.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, nivel.upper(), logging.INFO))

    if logger.handlers:
        return logger

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_name = Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "pipeline"
    log_file = log_dir / f"{timestamp}_{script_name}.log"

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.propagate = False
    logger.info("Log de esta corrida: %s", log_file)
    return logger
