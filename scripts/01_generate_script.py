#!/usr/bin/env python3
"""Genera guiones candidatos para el video del día usando Groq y deja elegir uno.

Uso:
    python scripts/01_generate_script.py
    python scripts/01_generate_script.py --idea "un bug clasico de C++"
    python scripts/01_generate_script.py --nicho programacion --idea "recursividad"

Guarda el guion elegido en output/guion_del_dia.txt y termina (no espera a
que grabes la narración: esa es una pausa manual fuera de este script, ver
docs/pipeline-automatizacion-reels.md).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from common.config import cargar_config  # noqa: E402
from common.guion import NICHOS_DEFAULT, elegir_nicho_por_rotacion, estimar_duracion_seg  # noqa: E402
from common.history import registrar_guion, temas_recientes  # noqa: E402
from common.llm_client import Candidato, GroqScriptClient, LLMResponseError  # noqa: E402
from common.logging_config import setup_logging  # noqa: E402


def mostrar_candidatos(
    candidatos: list[Candidato], duraciones: list[float], rango: tuple[float, float]
) -> None:
    minimo, maximo = rango
    print("\nGuiones candidatos:")
    print("=" * 60)
    for i, (candidato, duracion) in enumerate(zip(candidatos, duraciones), start=1):
        dentro_rango = minimo <= duracion <= maximo
        marca = "OK" if dentro_rango else "FUERA DE RANGO"
        print(f"\n[{i}] {candidato.titulo}  (~{duracion}s, {marca})")
        print("-" * 60)
        print(candidato.guion)
        if candidato.palabras_clave:
            print(f"\nPalabras clave: {', '.join(candidato.palabras_clave)}")
    print("\n" + "=" * 60)
    print(f"Rango objetivo de duración: {minimo}-{maximo}s")


def pedir_seleccion(cantidad: int) -> str:
    while True:
        respuesta = input(
            f"\nElegí un guion [1-{cantidad}], 'r' para regenerar, o 'q' para salir sin guardar: "
        ).strip().lower()
        if respuesta in ("q", "r"):
            return respuesta
        if respuesta.isdigit() and 1 <= int(respuesta) <= cantidad:
            return respuesta
        print("Opción inválida, probá de nuevo.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera el guion del día con Groq.")
    parser.add_argument("--idea", help="Tema puntual para el guion (opcional).")
    parser.add_argument(
        "--nicho",
        help=(
            "Forzar un nicho/categoría puntual (opcional). Puede ser cualquier texto libre "
            f"(ej. 'astrologia', 'recetas veganas'), no hace falta que esté en la lista de "
            f"rotación configurada ({', '.join(NICHOS_DEFAULT)}, ...)."
        ),
    )
    parser.add_argument(
        "--config",
        default=str(BASE_DIR / "config" / "settings.yaml"),
        help="Ruta a settings.yaml (por defecto config/settings.yaml).",
    )
    args = parser.parse_args()

    config = cargar_config(Path(args.config))
    logging_cfg = config.get("logging", {}) or {}
    logger = setup_logging(
        log_dir=BASE_DIR / logging_cfg.get("ruta", "logs"),
        nivel=logging_cfg.get("nivel", "INFO"),
    )

    guion_cfg = config.get("guion", {}) or {}
    llm_cfg = config.get("llm", {}) or {}
    historial_cfg = config.get("historial", {}) or {}

    nichos = guion_cfg.get("nichos") or NICHOS_DEFAULT
    historial_ruta = BASE_DIR / historial_cfg.get("ruta", "history/historial_guiones.json")
    evitar_dias = historial_cfg.get("evitar_repetir_dias", 14)
    palabras_por_minuto = guion_cfg.get("palabras_por_minuto", 150)
    rango_cfg = guion_cfg.get("duracion_objetivo_seg", [60, 90])
    rango = (float(rango_cfg[0]), float(rango_cfg[1]))

    nicho = args.nicho or elegir_nicho_por_rotacion(nichos, historial_ruta)
    evitar = temas_recientes(historial_ruta, nicho, dias=evitar_dias)
    if evitar:
        logger.info("Evitando repetir estos temas recientes de '%s': %s", nicho, evitar)

    try:
        cliente = GroqScriptClient(
            api_key=llm_cfg.get("groq_api_key"),
            modelo=llm_cfg.get("modelo", "openai/gpt-oss-20b"),
            max_reintentos=llm_cfg.get("max_reintentos", 3),
        )
    except RuntimeError as exc:
        logger.error(str(exc))
        print(f"\n{exc}")
        return 1

    n = llm_cfg.get("candidatos_por_ejecucion", 3)

    while True:
        try:
            candidatos = cliente.generar_candidatos(nicho, args.idea, n, evitar)
        except LLMResponseError as exc:
            logger.error("Groq no devolvió candidatos usables después de reintentar: %s", exc)
            print(f"\nNo se pudo generar el guion: {exc}")
            return 1
        except Exception as exc:  # noqa: BLE001 - falla de red/API ya reintentada, se informa y se corta
            logger.error("Fallo llamando a Groq después de reintentar: %s", exc)
            print(f"\nNo se pudo generar el guion (falló la API de Groq): {exc}")
            return 1

        duraciones = [estimar_duracion_seg(c.guion, palabras_por_minuto) for c in candidatos]
        mostrar_candidatos(candidatos, duraciones, rango)
        seleccion = pedir_seleccion(len(candidatos))

        if seleccion == "q":
            print("Cancelado, no se guardó ningún guion.")
            return 0
        if seleccion == "r":
            logger.info("Usuario pidió regenerar candidatos para nicho=%s.", nicho)
            continue
        break

    idx = int(seleccion) - 1
    elegido = candidatos[idx]
    duracion_elegida = duraciones[idx]

    output_dir = BASE_DIR / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    salida = output_dir / "guion_del_dia.txt"
    salida.write_text(elegido.guion + "\n", encoding="utf-8")

    registrar_guion(
        historial_ruta,
        {
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "nicho": nicho,
            "idea": args.idea,
            "titulo": elegido.titulo,
            "duracion_estimada_seg": duracion_elegida,
            "palabras_clave": elegido.palabras_clave,
        },
    )

    logger.info("Guion elegido guardado en %s (nicho=%s, ~%ss).", salida, nicho, duracion_elegida)
    print(f"\nGuardado en: {salida}")
    print("Ahora podés grabar tu narración y guardarla en input_audio/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
