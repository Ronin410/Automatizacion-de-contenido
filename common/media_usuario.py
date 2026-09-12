"""Media propia (fotos/clips) que el usuario sube para usar como B-roll.

Además del B-roll que se busca automáticamente en Pexels/Pixabay, cualquiera
puede subir sus propias fotos o videos cortos para que aparezcan en el video
final — más original, o simplemente porque ya tiene el material a mano.

Los archivos quedan "pendientes" hasta que se arma el próximo video: en ese
momento se consumen (se mueven a `usados/<timestamp>/`) para no reusarlos
por accidente en un video futuro sin relación.
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
class ClipMedia:
    """Misma forma que ClipBroll (ruta_local, tipo, query) para poder mezclarlos sin distinción
    en `04_assemble_video.py`."""

    ruta_local: Path
    tipo: str  # "video" | "imagen"
    query: str = "media_propia"


def _carpeta_pendientes(base_dir: Path) -> Path:
    carpeta = base_dir / "assets" / "media_usuario" / "pendiente"
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
    # timestamp con microsegundos para no pisar dos subidas en el mismo segundo
    nombre_seguro = f"{datetime.now().strftime('%Y%m%d_%H%M%S%f')}{extension}"
    (carpeta / nombre_seguro).write_bytes(contenido)
    logger.info("Media propia agregada a la cola: %s (%d bytes).", nombre_seguro, len(contenido))
    return {"nombre": nombre_seguro, "tipo": "video" if extension in EXTENSIONES_VIDEO else "imagen"}


def eliminar_pendiente(base_dir: Path, nombre: str) -> bool:
    carpeta = _carpeta_pendientes(base_dir)
    ruta = (carpeta / nombre).resolve()
    if carpeta.resolve() != ruta.parent:
        # nombre con "/" o "../" intentando salirse de la carpeta de pendientes
        raise ValueError("Nombre de archivo inválido.")
    if not ruta.exists():
        return False
    ruta.unlink()
    logger.info("Media propia eliminada de la cola: %s", nombre)
    return True


def tomar_pendientes_como_clips(base_dir: Path) -> list[ClipMedia]:
    """Devuelve los clips pendientes y los mueve a `usados/` (se consumen una sola vez)."""
    carpeta = _carpeta_pendientes(base_dir)
    archivos = sorted(p for p in carpeta.iterdir() if p.is_file())
    if not archivos:
        return []

    destino = base_dir / "assets" / "media_usuario" / "usados" / datetime.now().strftime("%Y%m%d_%H%M%S")
    destino.mkdir(parents=True, exist_ok=True)

    clips = []
    for archivo in archivos:
        nuevo_path = destino / archivo.name
        shutil.move(str(archivo), str(nuevo_path))
        tipo = "video" if archivo.suffix.lower() in EXTENSIONES_VIDEO else "imagen"
        clips.append(ClipMedia(ruta_local=nuevo_path, tipo=tipo))

    logger.info("Se usaron %d archivo(s) de media propia para este video.", len(clips))
    return clips
