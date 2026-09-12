"""Helpers puros sobre guiones: rotación de nicho y estimación de duración.

Compartidos por `scripts/01_generate_script.py` (CLI) y por la webapp, para
no duplicar esta lógica en los dos lados.
"""
from __future__ import annotations

from pathlib import Path

from common.history import ultimo_nicho

# Lista por defecto para la ROTACIÓN AUTOMÁTICA (cuando no se fuerza un nicho
# puntual). No es una lista cerrada: tanto la CLI (--nicho) como la webapp
# aceptan cualquier texto libre como override puntual, sin tener que estar
# en esta lista ni tocar código — útil para que cada persona que use el
# pipeline (ej. varias personas en la misma familia/equipo) escriba su propio
# ámbito sin que un dev tenga que agregarlo antes.
NICHOS_DEFAULT = [
    "tecnologia",
    "programacion",
    "videojuegos",
    "peliculas",
    "belleza",
    "moda",
    "cocina",
    "salud_bienestar",
    "fitness",
    "finanzas_personales",
    "viajes",
    "mascotas",
    "curiosidades",
    "motivacion",
    "humor",
    "diy_manualidades",
]


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


def keywords_para_broll(entrada: dict | None) -> list[str]:
    """Palabras clave del guion (las que eligió el LLM) + el nicho, para buscar B-roll.

    El respaldo genérico ante palabras clave sin resultados (ej. un nombre de
    marca que el banco de stock no tiene) se maneja en `BrollClient`, no acá.
    """
    keywords: list[str] = []
    if entrada and entrada.get("palabras_clave"):
        keywords.extend(entrada["palabras_clave"])
    if entrada and entrada.get("nicho") and entrada["nicho"] not in keywords:
        keywords.append(entrada["nicho"])
    return keywords
