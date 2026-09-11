"""Helpers puros sobre guiones: rotación de nicho y estimación de duración.

Compartidos por `scripts/01_generate_script.py` (CLI) y por la webapp, para
no duplicar esta lógica en los dos lados.
"""
from __future__ import annotations

from pathlib import Path

from common.history import ultimo_nicho

NICHOS_DEFAULT = ["tecnologia", "programacion", "videojuegos", "peliculas"]


def elegir_nicho_por_rotacion(nichos: list[str], historial_ruta: str | Path) -> str:
    """Rotación fija: el siguiente nicho en la lista después del último usado."""
    ultimo = ultimo_nicho(historial_ruta)
    if ultimo in nichos:
        idx = (nichos.index(ultimo) + 1) % len(nichos)
    else:
        idx = 0
    return nichos[idx]


def estimar_duracion_seg(texto: str, palabras_por_minuto: int) -> float:
    n_palabras = len(texto.split())
    return round((n_palabras / palabras_por_minuto) * 60, 1)
