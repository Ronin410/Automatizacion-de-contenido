"""Historial de guiones/temas usados por nicho.

Se guarda como una lista de entradas en un JSON (`history/historial_guiones.json`
por defecto). Sirve para:

- Evitar que el LLM repita el mismo subtema dentro de un nicho en poco tiempo
  (`temas_recientes`).
- Saber cuál fue el último nicho usado, para la rotación automática cuando el
  usuario no fuerza un nicho puntual (`ultimo_nicho`).
- Dejar datos ya listos para la analítica de la Fase 3 del pipeline.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from common.logging_config import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)


def _cargar(ruta: Path) -> list[dict[str, Any]]:
    if not ruta.exists():
        return []
    try:
        with ruta.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("No se pudo leer el historial en %s (%s); se empieza uno nuevo.", ruta, exc)
        return []
    return data if isinstance(data, list) else []


def registrar_guion(ruta: str | Path, entrada: dict[str, Any]) -> None:
    """Agrega una entrada al historial de guiones (crea el archivo si no existe)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    historial = _cargar(ruta)
    historial.append(entrada)
    with ruta.open("w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)
    logger.info("Historial actualizado en %s (%d entradas).", ruta, len(historial))


def temas_recientes(ruta: str | Path, nicho: str, dias: int = 14) -> list[str]:
    """Devuelve los títulos/temas usados para `nicho` en los últimos `dias` días."""
    historial = _cargar(Path(ruta))
    limite = datetime.now() - timedelta(days=dias)
    recientes = []
    for entrada in historial:
        if entrada.get("nicho") != nicho:
            continue
        try:
            fecha = datetime.fromisoformat(entrada.get("fecha", ""))
        except ValueError:
            continue
        if fecha >= limite:
            tema = entrada.get("titulo") or entrada.get("idea") or ""
            if tema:
                recientes.append(tema)
    return recientes


def ultimo_nicho(ruta: str | Path) -> str | None:
    """Devuelve el nicho de la última entrada registrada, o None si no hay historial."""
    historial = _cargar(Path(ruta))
    if not historial:
        return None
    return historial[-1].get("nicho")


def ultima_entrada(ruta: str | Path) -> dict[str, Any] | None:
    """Devuelve la última entrada registrada (el guion más reciente), o None si no hay historial."""
    historial = _cargar(Path(ruta))
    return historial[-1] if historial else None


def actualizar_ultima_entrada(ruta: str | Path, campos: dict[str, Any]) -> None:
    """Mezcla `campos` en la última entrada del historial (por ejemplo, la ruta del video final).

    No falla si el historial está vacío: en ese caso no hace nada, solo avisa por log.
    """
    ruta = Path(ruta)
    historial = _cargar(ruta)
    if not historial:
        logger.warning("No hay entradas en el historial (%s) para actualizar; se omite.", ruta)
        return
    historial[-1].update(campos)
    with ruta.open("w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=2)
    logger.info("Última entrada del historial actualizada con: %s", list(campos.keys()))
