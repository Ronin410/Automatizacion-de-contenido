#!/usr/bin/env python3
"""Vigila input_audio/ y dispara 02_finalizar.py automáticamente al detectar un audio nuevo.

Alternativa opcional al flujo manual: en vez de grabar y después acordarte de
volver a la terminal a correr `02_finalizar.py`, dejás este script corriendo
en una terminal aparte mientras grabás.

Uso:
    python scripts/watch_audio.py
    (Ctrl+C para salir)
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from common.logging_config import setup_logging  # noqa: E402

AUDIO_EXTENSIONES = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}
ESPERA_ESTABILIDAD_SEG = 2.0  # tiempo sin cambios de tamaño para asumir que la copia terminó


class ManejadorAudioNuevo(FileSystemEventHandler):
    def __init__(self, logger: logging.Logger):
        self._logger = logger
        self._temporizadores: dict[Path, threading.Timer] = {}

    def _es_audio_valido(self, ruta: Path) -> bool:
        return ruta.suffix.lower() in AUDIO_EXTENSIONES and not ruta.name.startswith(".")

    def _programar_verificacion(self, ruta: Path) -> None:
        anterior = self._temporizadores.pop(ruta, None)
        if anterior is not None:
            anterior.cancel()
        temporizador = threading.Timer(ESPERA_ESTABILIDAD_SEG, self._verificar_estable, args=(ruta,))
        self._temporizadores[ruta] = temporizador
        temporizador.start()

    def _verificar_estable(self, ruta: Path) -> None:
        self._temporizadores.pop(ruta, None)
        if not ruta.exists():
            return
        tamano_1 = ruta.stat().st_size
        time.sleep(ESPERA_ESTABILIDAD_SEG)
        if not ruta.exists() or ruta.stat().st_size != tamano_1:
            # todavía se está copiando/grabando; se reprograma
            self._programar_verificacion(ruta)
            return
        self._disparar_finalizar(ruta)

    def _disparar_finalizar(self, ruta: Path) -> None:
        self._logger.info("Audio nuevo detectado y estable: %s. Corriendo 02_finalizar.py...", ruta)
        print(f"\nAudio nuevo detectado: {ruta}\nProcesando (esto puede tardar unos minutos)...")
        resultado = subprocess.run(
            [sys.executable, str(BASE_DIR / "scripts" / "02_finalizar.py")],
            cwd=str(BASE_DIR),
        )
        if resultado.returncode == 0:
            self._logger.info("02_finalizar.py terminó OK para %s.", ruta)
            print("Listo. Podés seguir grabando el siguiente guion; sigo vigilando input_audio/.")
        else:
            self._logger.error("02_finalizar.py terminó con error (código %d) para %s.", resultado.returncode, ruta)
            print("02_finalizar.py falló, revisá el log. Sigo vigilando input_audio/ para el próximo intento.")

    def on_created(self, event):
        if not event.is_directory:
            ruta = Path(event.src_path)
            if self._es_audio_valido(ruta):
                self._programar_verificacion(ruta)

    def on_modified(self, event):
        if not event.is_directory:
            ruta = Path(event.src_path)
            if self._es_audio_valido(ruta):
                self._programar_verificacion(ruta)


def main() -> int:
    logger = setup_logging(log_dir=BASE_DIR / "logs")
    carpeta = BASE_DIR / "input_audio"
    carpeta.mkdir(parents=True, exist_ok=True)

    logger.info("Vigilando %s (Ctrl+C para salir)...", carpeta)
    print(f"Vigilando {carpeta} — grabá tu narración y guardala ahí. Ctrl+C para salir.")

    manejador = ManejadorAudioNuevo(logger)
    observer = Observer()
    observer.schedule(manejador, str(carpeta), recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Watcher detenido por el usuario.")
    finally:
        observer.stop()
        observer.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
