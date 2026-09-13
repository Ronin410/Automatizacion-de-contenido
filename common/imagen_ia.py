"""Generación de imágenes por IA — gratis, sin API key (Pollinations.ai).

Se usa como alternativa/complemento a los bancos de stock (Pexels/Pixabay)
para temas que un banco de fotos genéricas no va a tener (personajes de
videojuegos, algo muy específico de un nicho, etc.) y para generar
overlays/stickers a pedido.

Importante sobre qué pedirle: esto genera arte ORIGINAL inspirado en un
prompt, no una copia de algo con marca registrada. Evitá pedir personajes o
franquicias puntuales (Mario, Pikachu, etc.) tal cual — describí la escena o
el estilo de forma genérica (ej. "personaje de karting estilo videojuego,
colorido, orejas grandes" en vez del nombre del personaje). Qué tan cerca
quede el resultado de algo con copyright depende del prompt que le des, y
esa responsabilidad es de quien lo genera y lo publica — igual que con
cualquier herramienta de IA generativa de imágenes.

No requiere cuenta ni API key: es un servicio público gratuito, así que
puede ser menos confiable que una API paga (por eso los reintentos).
"""
from __future__ import annotations

import logging
import urllib.parse

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from common.logging_config import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)

TIMEOUT_SEG = 45  # generar una imagen tarda más que una búsqueda normal


def generar_imagen(prompt: str, ancho: int = 768, alto: int = 1365, max_reintentos: int = 3) -> bytes:
    """Genera una imagen a partir de `prompt` y devuelve los bytes (jpg/png)."""

    @retry(
        reraise=True,
        stop=stop_after_attempt(max_reintentos),
        wait=wait_exponential(multiplier=3, min=3, max=40),
    )
    def _llamar() -> bytes:
        url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt)
        logger.info("Generando imagen con IA: %r (%dx%d)...", prompt[:80], ancho, alto)
        try:
            resp = requests.get(
                url,
                params={"width": ancho, "height": alto, "nologo": "true"},
                timeout=TIMEOUT_SEG,
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - servicio publico gratuito, sin SLA; se reintenta y se loguea
            logger.warning("Fallo generando imagen con IA: %s", exc)
            raise
        return resp.content

    return _llamar()
