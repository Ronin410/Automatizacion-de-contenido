"""Wrapper de Groq para generar guiones candidatos, con reintentos y logging.

Aísla el resto del pipeline de los detalles de la API de Groq: si en el
futuro se agrega un proveedor de respaldo (por ejemplo Gemini), solo hay que
tocar este módulo.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field

from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential

from common.logging_config import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)


class LLMResponseError(Exception):
    """La respuesta del LLM no vino en el formato esperado (JSON con candidatos)."""


@dataclass
class Candidato:
    titulo: str
    guion: str
    palabras_clave: list[str] = field(default_factory=list)


def _resolver_api_key(settings_key: str | None) -> str:
    """Prioriza la variable de entorno GROQ_API_KEY; si no existe, usa la de settings.yaml."""
    api_key = os.environ.get("GROQ_API_KEY")
    if api_key:
        return api_key
    if settings_key and not settings_key.startswith("${"):
        return settings_key
    raise RuntimeError(
        "No se encontró la API key de Groq. Definí la variable de entorno "
        "GROQ_API_KEY o completá 'llm.groq_api_key' en config/settings.yaml."
    )


def _construir_prompt(nicho: str, idea: str | None, n: int, evitar: list[str]) -> str:
    if idea:
        contexto_idea = f'Tema puntual pedido por el usuario: "{idea}".'
    else:
        contexto_idea = "No hay un tema puntual: elegí un subtema interesante y variado dentro del nicho."

    evitar_texto = ""
    if evitar:
        evitar_texto = "\nNo repitas estos subtemas ya usados recientemente: " + "; ".join(evitar) + "."

    return f"""Sos un guionista de videos cortos (Shorts/Reels) de 60 a 90 segundos, en español,
para un canal del nicho "{nicho}". {contexto_idea}{evitar_texto}

Generá exactamente {n} guiones distintos entre sí (distinto ángulo o subtema cada uno).
Cada guion debe:
- Estar escrito para narrarse en voz alta (frases cortas, tono conversacional).
- Tener un gancho fuerte en las primeras dos frases.
- Durar entre 60 y 90 segundos al narrarlo a ritmo normal (aprox. 150-220 palabras).
- No incluir indicaciones de cámara ni edición, solo el texto a narrar.

Respondé ÚNICAMENTE con un array JSON válido, sin texto antes ni después ni bloques de código,
con esta forma exacta:
[
  {{"titulo": "...", "guion": "...", "palabras_clave": ["...", "..."]}}
]"""


def _parsear_candidatos(contenido: str) -> list[Candidato]:
    texto = contenido.strip()
    match = re.search(r"\[.*\]", texto, re.DOTALL)
    if match:
        texto = match.group(0)

    try:
        data = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise LLMResponseError(f"No se pudo interpretar la respuesta como JSON: {exc}") from exc

    if not isinstance(data, list) or not data:
        raise LLMResponseError("La respuesta JSON no es una lista de candidatos no vacía.")

    candidatos = []
    for item in data:
        if not isinstance(item, dict) or not item.get("guion"):
            raise LLMResponseError(f"Candidato con formato inesperado: {item!r}")
        candidatos.append(
            Candidato(
                titulo=str(item.get("titulo") or "").strip() or "(sin título)",
                guion=str(item["guion"]).strip(),
                palabras_clave=[str(k) for k in item.get("palabras_clave", [])],
            )
        )
    return candidatos


class GroqScriptClient:
    """Genera guiones candidatos vía Groq, con reintentos ante fallos de red/API/parseo."""

    def __init__(self, api_key: str | None, modelo: str, max_reintentos: int = 3):
        self._client = Groq(api_key=_resolver_api_key(api_key))
        self._modelo = modelo
        self._max_reintentos = max(1, max_reintentos)

    def generar_candidatos(
        self, nicho: str, idea: str | None, n: int, evitar: list[str] | None = None
    ) -> list[Candidato]:
        prompt = _construir_prompt(nicho, idea, n, evitar or [])

        @retry(
            reraise=True,
            stop=stop_after_attempt(self._max_reintentos),
            wait=wait_exponential(multiplier=2, min=2, max=30),
        )
        def _llamar() -> list[Candidato]:
            logger.info(
                "Pidiendo %d guion(es) candidato(s) a Groq (modelo=%s, nicho=%s, idea=%s)...",
                n, self._modelo, nicho, idea or "-",
            )
            try:
                respuesta = self._client.chat.completions.create(
                    model=self._modelo,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.9,
                    # Generoso a propósito: algunos modelos (ej. los "razonadores" tipo
                    # gpt-oss) gastan varios cientos/miles de tokens pensando antes de
                    # escribir la respuesta final; con un límite chico se corta a mitad
                    # de un string o queda vacía (finish_reason="length").
                    max_tokens=4096,
                )
            except Exception as exc:  # noqa: BLE001 - cualquier error de red/API se reintenta y se loguea
                logger.warning("Fallo llamando a la API de Groq: %s", exc)
                raise

            choice = respuesta.choices[0]
            contenido = choice.message.content or ""
            if choice.finish_reason == "length":
                logger.warning(
                    "Groq cortó la respuesta por límite de tokens (finish_reason=length, "
                    "%d caracteres recibidos); se reintenta.", len(contenido),
                )
                raise LLMResponseError("Respuesta cortada por límite de tokens (finish_reason=length).")

            try:
                return _parsear_candidatos(contenido)
            except LLMResponseError as exc:
                preview = contenido[:300].replace("\n", " ")
                logger.warning(
                    "Respuesta de Groq no parseable, se reintenta: %s (preview: %r)", exc, preview
                )
                raise

        return _llamar()
