"""Overlays (memes/avatar/stickers) que aparecen flotando encima del video.

Distinto de la "media propia" de `common/media_usuario.py`: aquella
reemplaza tramos enteros de B-roll a pantalla completa; esto en cambio se
compone flotando en una esquina, por encima de lo que sea que esté pasando
en ese momento — pensado para memes, reacciones, un avatar/logo, etc.

Mismo patrón que `media_usuario.py`: quedan "pendientes" hasta que se arma
el próximo video, momento en el que se consumen (se mueven a `usados/`).
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from common.logging_config import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)

EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".webp"}
EXTENSIONES_VIDEO = {".mp4", ".mov", ".mkv", ".webm"}
EXTENSIONES_PERMITIDAS = EXTENSIONES_IMAGEN | EXTENSIONES_VIDEO


@dataclass
class Overlay:
    ruta_local: Path
    tipo: str  # "video" | "imagen"


def _carpeta_pendientes(base_dir: Path) -> Path:
    carpeta = base_dir / "assets" / "overlays_usuario" / "pendiente"
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def listar_pendientes(base_dir: Path) -> list[dict]:
    carpeta = _carpeta_pendientes(base_dir)
    archivos = sorted((p for p in carpeta.iterdir() if p.is_file()), key=lambda p: p.name)
    return [
        {"nombre": p.name, "tipo": "video" if p.suffix.lower() in EXTENSIONES_VIDEO else "imagen"}
        for p in archivos
    ]


def agregar_pendiente(base_dir: Path, nombre_original: str, contenido: bytes) -> dict:
    extension = Path(nombre_original).suffix.lower()
    if extension not in EXTENSIONES_PERMITIDAS:
        raise ValueError(
            f"Extensión no soportada: {extension!r} (usar {sorted(EXTENSIONES_PERMITIDAS)})."
        )
    carpeta = _carpeta_pendientes(base_dir)
    nombre_seguro = f"{datetime.now().strftime('%Y%m%d_%H%M%S%f')}{extension}"
    (carpeta / nombre_seguro).write_bytes(contenido)
    logger.info("Overlay agregado a la cola: %s (%d bytes).", nombre_seguro, len(contenido))
    return {"nombre": nombre_seguro, "tipo": "video" if extension in EXTENSIONES_VIDEO else "imagen"}


def eliminar_pendiente(base_dir: Path, nombre: str) -> bool:
    carpeta = _carpeta_pendientes(base_dir)
    ruta = (carpeta / nombre).resolve()
    if carpeta.resolve() != ruta.parent:
        raise ValueError("Nombre de archivo inválido.")
    if not ruta.exists():
        return False
    ruta.unlink()
    logger.info("Overlay eliminado de la cola: %s", nombre)
    return True


def tomar_pendientes(base_dir: Path) -> list[Overlay]:
    """Devuelve los overlays pendientes y los mueve a `usados/` (se consumen una sola vez)."""
    carpeta = _carpeta_pendientes(base_dir)
    archivos = sorted(p for p in carpeta.iterdir() if p.is_file())
    if not archivos:
        return []

    destino = base_dir / "assets" / "overlays_usuario" / "usados" / datetime.now().strftime("%Y%m%d_%H%M%S")
    destino.mkdir(parents=True, exist_ok=True)

    overlays = []
    for archivo in archivos:
        nuevo_path = destino / archivo.name
        shutil.move(str(archivo), str(nuevo_path))
        tipo = "video" if archivo.suffix.lower() in EXTENSIONES_VIDEO else "imagen"
        overlays.append(Overlay(ruta_local=nuevo_path, tipo=tipo))

    logger.info("Se usaron %d overlay(s) para este video.", len(overlays))
    return overlays
