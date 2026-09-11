"""Carga de config/settings.yaml, compartida por los scripts de CLI y la webapp."""
from __future__ import annotations

from pathlib import Path

import yaml


def cargar_config(ruta: str | Path) -> dict:
    ruta = Path(ruta)
    if not ruta.exists():
        ejemplo = ruta.parent / "settings.example.yaml"
        raise FileNotFoundError(
            f"No existe {ruta}. Copiá {ejemplo.name} a {ruta.name} en la misma carpeta "
            "y completá tus API keys (o definí las variables de entorno correspondientes)."
        )
    with ruta.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
