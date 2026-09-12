#!/usr/bin/env python3
"""Busca y descarga B-roll (video o imagen) desde Pexels o Pixabay según palabras clave.

Prioriza clips de video (más producción que una foto fija); si un keyword no
tiene resultados de video, cae a foto. Cada búsqueda/descarga usa reintentos
con backoff (vía tenacity) ante fallos de red o límites de cuota.
"""
from __future__ import annotations

import logging
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from common.logging_config import LOGGER_NAME  # noqa: E402

logger = logging.getLogger(LOGGER_NAME)

TIMEOUT_SEG = 20

# Último recurso cuando una palabra clave puntual no da resultados (ej. el
# LLM eligió un término raro, o algo con copyright que el banco de stock
# no tiene) — "abstract background" prácticamente siempre tiene resultados
# en Pexels/Pixabay, así una sola palabra clave floja no tira todo el video.
KEYWORD_RESPALDO = "abstract background"


class BrollError(Exception):
    """No se pudo obtener B-roll para ninguna de las palabras clave dadas."""


@dataclass
class ClipBroll:
    ruta_local: Path
    tipo: str  # "video" | "imagen"
    query: str


def _resolver_api_key(proveedor: str, settings_key: str | None) -> str:
    env_var = "PEXELS_API_KEY" if proveedor == "pexels" else "PIXABAY_API_KEY"
    api_key = os.environ.get(env_var)
    if api_key:
        return api_key
    if settings_key and not settings_key.startswith("${"):
        return settings_key
    raise RuntimeError(
        f"No se encontró la API key de {proveedor}. Definí la variable de entorno "
        f"{env_var} o completá 'broll.api_key' en config/settings.yaml."
    )


def _descargar(url: str, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=TIMEOUT_SEG) as resp:
        resp.raise_for_status()
        with destino.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                f.write(chunk)


def _buscar_pexels_video(api_key: str, query: str) -> str | None:
    resp = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": api_key},
        params={"query": query, "orientation": "portrait", "per_page": 10},
        timeout=TIMEOUT_SEG,
    )
    resp.raise_for_status()
    videos = resp.json().get("videos", [])
    if not videos:
        return None
    video = random.choice(videos)
    archivos = sorted(video.get("video_files", []), key=lambda vf: vf.get("width") or 0)
    candidatos = [vf for vf in archivos if (vf.get("width") or 0) >= 720] or archivos
    return candidatos[0]["link"] if candidatos else None


def _buscar_pexels_foto(api_key: str, query: str) -> str | None:
    resp = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": api_key},
        params={"query": query, "orientation": "portrait", "per_page": 10},
        timeout=TIMEOUT_SEG,
    )
    resp.raise_for_status()
    fotos = resp.json().get("photos", [])
    if not fotos:
        return None
    foto = random.choice(fotos)
    return foto["src"]["large2x"]


def _buscar_pixabay_video(api_key: str, query: str) -> str | None:
    resp = requests.get(
        "https://pixabay.com/api/videos/",
        params={"key": api_key, "q": query, "per_page": 10},
        timeout=TIMEOUT_SEG,
    )
    resp.raise_for_status()
    hits = resp.json().get("hits", [])
    if not hits:
        return None
    hit = random.choice(hits)
    videos = hit.get("videos", {})
    for calidad in ("medium", "small", "large", "tiny"):
        if calidad in videos:
            return videos[calidad]["url"]
    return None


def _buscar_pixabay_foto(api_key: str, query: str) -> str | None:
    resp = requests.get(
        "https://pixabay.com/api/",
        params={"key": api_key, "q": query, "per_page": 10, "orientation": "vertical"},
        timeout=TIMEOUT_SEG,
    )
    resp.raise_for_status()
    hits = resp.json().get("hits", [])
    if not hits:
        return None
    hit = random.choice(hits)
    return hit.get("largeImageURL") or hit.get("webformatURL")


_BUSCADORES = {
    "pexels": {"video": _buscar_pexels_video, "imagen": _buscar_pexels_foto},
    "pixabay": {"video": _buscar_pixabay_video, "imagen": _buscar_pixabay_foto},
}


class BrollClient:
    def __init__(self, proveedor: str, api_key: str | None, max_reintentos: int = 3):
        if proveedor not in _BUSCADORES:
            raise ValueError(f"Proveedor de B-roll desconocido: {proveedor!r} (usar 'pexels' o 'pixabay')")
        self._proveedor = proveedor
        self._api_key = _resolver_api_key(proveedor, api_key)
        self._max_reintentos = max(1, max_reintentos)

    def _con_reintentos(self, func, *args):
        @retry(
            reraise=True,
            stop=stop_after_attempt(self._max_reintentos),
            wait=wait_exponential(multiplier=2, min=2, max=30),
        )
        def _llamar():
            try:
                return func(self._api_key, *args)
            except Exception as exc:  # noqa: BLE001 - error de red/API, se reintenta y se loguea
                logger.warning("Fallo consultando %s: %s", self._proveedor, exc)
                raise

        return _llamar()

    def buscar_una(self, query: str) -> tuple[str, str] | None:
        """Busca video primero; si no hay, cae a foto. Devuelve (url, tipo) o None."""
        buscadores = _BUSCADORES[self._proveedor]
        url = self._con_reintentos(buscadores["video"], query)
        if url:
            return url, "video"
        url = self._con_reintentos(buscadores["imagen"], query)
        if url:
            return url, "imagen"
        return None

    def buscar_y_descargar(self, keywords: list[str], cantidad: int, destino: Path) -> list[ClipBroll]:
        """Descarga `cantidad` clips, rotando entre `keywords` (se repiten si hacen falta más).

        Si una palabra clave puntual no da resultados (ej. el LLM eligió un
        término raro, o quedó algo con copyright que el banco de stock no
        tiene), se reintenta esa misma posición con `KEYWORD_RESPALDO` en vez
        de simplemente perder el clip — evita que el video entero falle por
        una sola palabra clave floja.
        """
        if not keywords:
            keywords = [KEYWORD_RESPALDO]

        destino = Path(destino)
        destino.mkdir(parents=True, exist_ok=True)
        clips: list[ClipBroll] = []

        for i in range(cantidad):
            query = keywords[i % len(keywords)]
            logger.info("Buscando B-roll (%d/%d) para '%s' en %s...", i + 1, cantidad, query, self._proveedor)
            resultado = self.buscar_una(query)
            if resultado is None and query != KEYWORD_RESPALDO:
                logger.info("Sin resultados para '%s', probando respaldo genérico '%s'...", query, KEYWORD_RESPALDO)
                query = KEYWORD_RESPALDO
                resultado = self.buscar_una(query)
            if resultado is None:
                logger.warning("Sin resultados de B-roll para '%s', se omite.", query)
                continue

            url, tipo = resultado
            extension = ".mp4" if tipo == "video" else ".jpg"
            ruta_local = destino / f"broll_{i + 1:02d}_{query.replace(' ', '_')}{extension}"
            try:
                self._con_reintentos(lambda _key, u=url, r=ruta_local: _descargar(u, r))
            except Exception as exc:  # noqa: BLE001 - ya se reintentó, se loguea y se sigue con el resto
                logger.error("No se pudo descargar B-roll para '%s': %s", query, exc)
                continue

            clips.append(ClipBroll(ruta_local=ruta_local, tipo=tipo, query=query))

        if not clips:
            raise BrollError(
                f"No se consiguió ningún B-roll para las palabras clave {keywords!r}. "
                "Revisá la API key y la cuota del proveedor configurado."
            )
        return clips
