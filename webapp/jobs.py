"""Cola simple de trabajos en background para procesar un audio a la vez.

Se eligió una cola con un solo worker (en vez de lanzar un thread por
request) a propósito: la VM donde corre esto (pensada para ser gratis, ej.
Oracle Cloud Free Tier) tiene RAM/CPU limitada, y Whisper + MoviePy ya usan
bastante de las dos. Procesar de a uno evita que dos requests de audio se
pisen y agoten la memoria.

El estado de los trabajos vive solo en memoria (se pierde si el proceso se
reinicia); el video ya generado, en cambio, queda en output_videos/ y su
ruta también se registra en history/historial_guiones.json.
"""
from __future__ import annotations

import logging
import queue
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from common.logging_config import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)


@dataclass
class Trabajo:
    id: str
    audio_path: str
    estado: str = "en_cola"  # en_cola | procesando | listo | error
    video_path: str | None = None
    error: str | None = None
    creado: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    actualizado: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "estado": self.estado,
            "video_path": self.video_path,
            "error": self.error,
            "creado": self.creado,
            "actualizado": self.actualizado,
        }


class GestorTrabajos:
    """Procesa audios uno a la vez en un thread de fondo, con estado consultable por id."""

    def __init__(self, procesar_audio: Callable[[Path], Path]):
        self._procesar_audio = procesar_audio
        self._trabajos: dict[str, Trabajo] = {}
        self._ultimo_id: str | None = None
        self._cola: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._hilo = threading.Thread(target=self._bucle, daemon=True, name="gestor-trabajos")
        self._hilo.start()

    def encolar(self, audio_path: Path) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._trabajos[job_id] = Trabajo(id=job_id, audio_path=str(audio_path))
            self._ultimo_id = job_id
        self._cola.put(job_id)
        logger.info("Trabajo %s encolado para %s (posición en cola: %d).", job_id, audio_path, self._cola.qsize())
        return job_id

    def estado(self, job_id: str) -> Trabajo | None:
        with self._lock:
            return self._trabajos.get(job_id)

    def ultimo(self) -> Trabajo | None:
        """Devuelve el trabajo más reciente (para recuperar el estado tras un refresh de página)."""
        with self._lock:
            return self._trabajos.get(self._ultimo_id) if self._ultimo_id else None

    def _actualizar(self, job_id: str, **campos) -> None:
        with self._lock:
            trabajo = self._trabajos[job_id]
            for clave, valor in campos.items():
                setattr(trabajo, clave, valor)
            trabajo.actualizado = datetime.now().isoformat(timespec="seconds")

    def _bucle(self) -> None:
        while True:
            job_id = self._cola.get()
            self._actualizar(job_id, estado="procesando")
            trabajo = self.estado(job_id)
            logger.info("Procesando trabajo %s (%s)...", job_id, trabajo.audio_path)
            try:
                video_path = self._procesar_audio(Path(trabajo.audio_path))
                self._actualizar(job_id, estado="listo", video_path=str(video_path))
                logger.info("Trabajo %s listo: %s", job_id, video_path)
            except Exception as exc:  # noqa: BLE001 - cualquier falla de la etapa final se refleja en el estado
                logger.exception("Trabajo %s falló.", job_id)
                self._actualizar(job_id, estado="error", error=str(exc))
