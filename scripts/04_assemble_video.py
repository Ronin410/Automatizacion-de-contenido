#!/usr/bin/env python3
"""Ensambla el video final: narración + B-roll + subtítulos incrustados + intro/outro.

Usa MoviePy 2.x. Los subtítulos se renderizan con `TextClip` (usa Pillow por
dentro en esta versión de MoviePy, no requiere tener ImageMagick instalado).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
)

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from common.logging_config import LOGGER_NAME  # noqa: E402

logger = logging.getLogger(LOGGER_NAME)

EXTENSIONES_VIDEO = {".mp4", ".mov", ".mkv", ".webm"}


def _redimensionar_cubrir(clip, ancho: int, alto: int):
    """Escala `clip` para cubrir ancho x alto y recorta el excedente (crop 'cover'), sin bordes."""
    escala = max(ancho / clip.w, alto / clip.h)
    clip = clip.resized(escala)
    return clip.cropped(width=ancho, height=alto, x_center=clip.w / 2, y_center=clip.h / 2)


def _clip_de_broll(ruta: Path, duracion: float, ancho: int, alto: int):
    if ruta.suffix.lower() in EXTENSIONES_VIDEO:
        clip = VideoFileClip(str(ruta))
        # si el clip de stock dura menos que la porción que le toca, se repite en loop
        if clip.duration < duracion:
            vueltas = int(duracion // clip.duration) + 1
            clip = concatenate_videoclips([clip] * vueltas)
        clip = clip.subclipped(0, duracion)
    else:
        clip = ImageClip(str(ruta)).with_duration(duracion)
    return _redimensionar_cubrir(clip, ancho, alto).with_duration(duracion)


def _clip_de_subtitulo(texto: str, inicio: float, fin: float, ancho_video: int, config_sub: dict):
    clip = TextClip(
        text=texto,
        font=config_sub.get("fuente") or None,
        font_size=config_sub.get("tam_fuente", 64),
        color=config_sub.get("color_texto", "white"),
        stroke_color=config_sub.get("color_borde", "black"),
        stroke_width=2,
        method="caption",
        size=(int(ancho_video * 0.9), None),
        text_align="center",
    )
    return clip.with_position(("center", 0.82), relative=True).with_start(inicio).with_end(fin)


def _clip_intro_outro(ruta: str | None, ancho: int, alto: int):
    if not ruta:
        return None
    ruta_path = BASE_DIR / ruta
    if not ruta_path.exists():
        logger.info("No hay intro/outro en %s, se omite.", ruta_path)
        return None
    clip = VideoFileClip(str(ruta_path))
    return _redimensionar_cubrir(clip, ancho, alto)


def ensamblar_video(
    audio_path: str | Path,
    subtitulos: list,
    broll_clips: list,
    salida: str | Path,
    video_cfg: dict,
) -> Path:
    """Combina audio + B-roll + subtítulos (+ intro/outro opcionales) y escribe el .mp4 final."""
    ancho = video_cfg.get("ancho", 1080)
    alto = video_cfg.get("alto", 1920)
    fps = video_cfg.get("fps", 30)

    audio = AudioFileClip(str(audio_path))
    duracion_total = audio.duration

    if not broll_clips:
        raise ValueError("No hay clips de B-roll para ensamblar el video.")

    n = len(broll_clips)
    duracion_por_clip = duracion_total / n
    logger.info("Armando %d segmento(s) de B-roll de ~%.1fs cada uno (total %.1fs).", n, duracion_por_clip, duracion_total)

    segmentos = [
        _clip_de_broll(clip.ruta_local, duracion_por_clip, ancho, alto) for clip in broll_clips
    ]
    video_base = concatenate_videoclips(segmentos, method="compose").with_duration(duracion_total)

    capas = [video_base]
    for sub in subtitulos:
        capas.append(_clip_de_subtitulo(sub.texto, sub.inicio, min(sub.fin, duracion_total), ancho, video_cfg))

    video_con_subs = CompositeVideoClip(capas, size=(ancho, alto)).with_duration(duracion_total)
    video_con_audio = video_con_subs.with_audio(audio)

    tramos = []
    intro = _clip_intro_outro(video_cfg.get("intro"), ancho, alto)
    if intro is not None:
        tramos.append(intro)
    tramos.append(video_con_audio)
    outro = _clip_intro_outro(video_cfg.get("outro"), ancho, alto)
    if outro is not None:
        tramos.append(outro)

    final = concatenate_videoclips(tramos, method="compose") if len(tramos) > 1 else video_con_audio

    salida = Path(salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Renderizando video final en %s...", salida)
    final.write_videofile(str(salida), fps=fps, codec="libx264", audio_codec="aac", logger=None)
    logger.info("Video final escrito en %s (%.1fs).", salida, final.duration)
    return salida
