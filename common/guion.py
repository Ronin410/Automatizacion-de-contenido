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
    "anime",
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


def resolver_ratio_ia(broll_cfg: dict, nicho: str | None) -> float:
    """Fracción de clips a generar con IA (ver `common/imagen_ia.py`), según nicho.

    `broll.ratio_ia` en la config es el default global. `broll.ratio_ia_por_nicho`
    permite subirlo para nichos puntuales sin tocar el default de los demás:
    justamente en nichos como anime/videojuegos/peliculas el banco de stock es
    donde menos resultados da (personajes/mundos con copyright que Pexels/Pixabay
    no tienen), así que ahí conviene un ratio más alto que el resto.
    """
    default = broll_cfg.get("ratio_ia", 0.0) or 0.0
    por_nicho = broll_cfg.get("ratio_ia_por_nicho") or {}
    if nicho and nicho in por_nicho:
        return por_nicho[nicho]
    return default
