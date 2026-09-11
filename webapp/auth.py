"""Autenticación mínima por token compartido.

Esta app queda expuesta a internet (para poder usarla desde cualquier
lado), así que todos los endpoints de la API requieren un header
`X-Api-Token` que coincida con la variable de entorno `WEBAPP_TOKEN`. No es
un sistema de usuarios — es un candado simple para que no cualquiera pueda
gastar tu cuota de Groq/Pexels o subir audios a tu servidor.
"""
from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException


def verificar_token(x_api_token: str | None = Header(default=None)) -> None:
    esperado = os.environ.get("WEBAPP_TOKEN")
    if not esperado:
        raise HTTPException(
            status_code=500,
            detail="El servidor no tiene configurada la variable de entorno WEBAPP_TOKEN.",
        )
    if not x_api_token or not secrets.compare_digest(x_api_token, esperado):
        raise HTTPException(status_code=401, detail="Token inválido o faltante (header X-Api-Token).")
