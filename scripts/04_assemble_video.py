#!/usr/bin/env python3
"""Ensambla el video final: narración + B-roll + subtítulos + overlays + música + intro/outro.

Usa MoviePy 2.x. Los subtítulos se renderizan con `TextClip` (usa Pillow por
dentro en esta versión de MoviePy, no requiere tener ImageMagick instalado).

Mejoras de calidad (v6, a partir de feedback sobre el primer video real):
- Transiciones con crossfade entre segmentos de B-roll (antes: corte seco).
- Cuando un clip de B-roll es más corto que su porción, se extiende en
  "boomerang" (ida y vuelta) en vez de reiniciar desde el frame 0 — evita el
  salto brusco de un loop común.
- Subtítulos con una fuente real (incluye tildes/ñ — la fuente default de
  MoviePy no las renderizaba bien) y una caja semitransparente detrás para
  que se lean sobre cualquier fondo.
- Overlays opcionales (memes/avatar/stickers) flotando en una esquina.
- Música de fondo opcional, mezclada por debajo de la narración.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    afx,
    concatenate_videoclips,
    vfx,
)

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from common.logging_config import LOGGER_NAME  # noqa: E402

logger = logging.getLogger(LOGGER_NAME)

EXTENSIONES_VIDEO = {".mp4", ".mov", ".mkv", ".webm"}
FUENTE_DEFAULT = BASE_DIR / "assets" / "fonts" / "BigShoulders-Bold.ttf"


def _redimensionar_cubrir(clip, ancho: int, alto: int):
    """Escala `clip` para cubrir ancho x alto y recorta el excedente (crop 'cover'), sin bordes."""
    escala = max(ancho / clip.w, alto / clip.h)
    clip = clip.resized(escala)
    return clip.cropped(width=ancho, height=alto, x_center=clip.w / 2, y_center=clip.h / 2)


def _loop_boomerang(clip, duracion: float):
    """Extiende `clip` a `duracion` reproduciendo ida-y-vuelta en vez de reiniciar desde el
    frame 0 — un loop normal da un salto visible; ida-y-vuelta es un ciclo sin costura."""
    vuelta = clip.with_effects([vfx.TimeMirror()])
    ciclo = concatenate_videoclips([clip, vuelta])
    vueltas = int(duracion // ciclo.duration) + 1
    return concatenate_videoclips([ciclo] * vueltas).subclipped(0, duracion)


def _clip_de_broll(ruta: Path, duracion: float, ancho: int, alto: int):
    if ruta.suffix.lower() in EXTENSIONES_VIDEO:
        clip = VideoFileClip(str(ruta))
        if clip.duration < duracion:
            clip = _loop_boomerang(clip, duracion)
        else:
            clip = clip.subclipped(0, duracion)
    else:
        clip = ImageClip(str(ruta)).with_duration(duracion)
    return _redimensionar_cubrir(clip, ancho, alto).with_duration(duracion)


def _armar_video_base(broll_clips: list, duracion_total: float, ancho: int, alto: int, transicion: float):
    """Concatena los segmentos de B-roll con crossfade entre ellos (si hay más de uno)."""
    n = len(broll_clips)
    if n == 1:
        clip = _clip_de_broll(broll_clips[0].ruta_local, duracion_total, ancho, alto)
        return clip.with_duration(duracion_total)

    # Cada segmento se hace un poco más largo que "duracion_total / n" para compensar
    # el tiempo que se pierde en los solapamientos del crossfade — así la duración
    # final sigue coincidiendo con la narración.
    base = duracion_total / n
    transicion = min(transicion, base * 0.3)
    duracion_por_clip = (duracion_total + (n - 1) * transicion) / n if transicion > 0 else base
    logger.info(
        "Armando %d segmento(s) de B-roll de ~%.1fs cada uno (transición %.2fs, total %.1fs).",
        n, duracion_por_clip, transicion, duracion_total,
    )

    segmentos = [_clip_de_broll(c.ruta_local, duracion_por_clip, ancho, alto) for c in broll_clips]
    if transicion > 0:
        segmentos = [segmentos[0]] + [
            s.with_effects([vfx.CrossFadeIn(transicion)]) for s in segmentos[1:]
        ]
        video_base = concatenate_videoclips(segmentos, method="compose", padding=-transicion)
    else:
        video_base = concatenate_videoclips(segmentos, method="compose")
    return video_base.with_duration(duracion_total)


def _clip_de_subtitulo(texto: str, inicio: float, fin: float, ancho_video: int, config_sub: dict):
    fuente = config_sub.get("fuente") or str(FUENTE_DEFAULT)
    texto_clip = TextClip(
        text=texto,
        font=fuente,
        font_size=config_sub.get("tam_fuente", 64),
        color=config_sub.get("color_texto", "white"),
        stroke_color=config_sub.get("color_borde", "black"),
        stroke_width=3,
        method="caption",
        size=(int(ancho_video * 0.85), None),
        text_align="center",
    )

    # Caja semitransparente detrás del texto: sin esto, un subtítulo blanco se
    # vuelve ilegible apenas el B-roll de fondo tiene una zona clara.
    padding_x, padding_y = 22, 14
    fondo = ColorClip(
        size=(texto_clip.w + padding_x * 2, texto_clip.h + padding_y * 2), color=(0, 0, 0)
    ).with_opacity(config_sub.get("subtitulo_fondo_opacidad", 0.45))

    grupo = CompositeVideoClip(
        [fondo.with_position("center"), texto_clip.with_position("center")], size=fondo.size
    )
    duracion = max(0.01, fin - inicio)
    return (
        grupo.with_duration(duracion)
        .with_start(inicio)
        .with_end(fin)
        .with_position(("center", config_sub.get("subtitulo_pos_y", 0.78)), relative=True)
    )


def _clips_de_overlays(overlays: list, duracion_total: float, ancho: int, alto: int):
    """Overlays (memes/avatar/stickers) flotando en la esquina superior derecha
    — a propósito arriba, no abajo, para no taparse con los subtítulos —
    apareciendo en momentos repartidos a lo largo del video."""
    if not overlays:
        return []

    duracion_cada_uno = min(3.0, max(1.5, duracion_total / (len(overlays) * 2 + 1)))
    ancho_overlay = int(ancho * 0.34)
    margen = int(ancho * 0.04)
    paso = duracion_total / (len(overlays) + 1)

    clips = []
    for i, overlay in enumerate(overlays):
        centro = paso * (i + 1)
        inicio = max(0.0, min(centro - duracion_cada_uno / 2, max(0.0, duracion_total - duracion_cada_uno)))
        fin = min(inicio + duracion_cada_uno, duracion_total)

        if overlay.tipo == "video":
            base = VideoFileClip(str(overlay.ruta_local))
            clip = base.subclipped(0, min(duracion_cada_uno, base.duration))
        else:
            clip = ImageClip(str(overlay.ruta_local)).with_duration(duracion_cada_uno)

        clip = clip.resized(width=ancho_overlay)
        pos_x = ancho - clip.w - margen
        pos_y = margen  # esquina superior, lejos de la franja de subtítulos de abajo
        clip = (
            clip.with_effects([vfx.FadeIn(0.25), vfx.FadeOut(0.25)])
            .with_position((pos_x, pos_y))
            .with_start(inicio)
            .with_end(fin)
        )
        clips.append(clip)
    return clips


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
    overlays: list | None = None,
    musica_path: str | Path | None = None,
    musica_volumen: float = 0.15,
) -> Path:
    """Combina audio + B-roll + subtítulos (+ overlays, música, intro/outro opcionales)."""
    ancho = video_cfg.get("ancho", 1080)
    alto = video_cfg.get("alto", 1920)
    fps = video_cfg.get("fps", 30)
    transicion = video_cfg.get("transicion_seg", 0.4)

    audio = AudioFileClip(str(audio_path))
    duracion_total = audio.duration

    if not broll_clips:
        raise ValueError("No hay clips de B-roll para ensamblar el video.")

    video_base = _armar_video_base(broll_clips, duracion_total, ancho, alto, transicion)

    capas = [video_base]
    for sub in subtitulos:
        capas.append(_clip_de_subtitulo(sub.texto, sub.inicio, min(sub.fin, duracion_total), ancho, video_cfg))
    capas.extend(_clips_de_overlays(overlays or [], duracion_total, ancho, alto))

    video_con_capas = CompositeVideoClip(capas, size=(ancho, alto)).with_duration(duracion_total)

    audio_final = audio
    if musica_path:
        try:
            musica = (
                AudioFileClip(str(musica_path))
                .with_effects([
                    afx.AudioLoop(duration=duracion_total),
                    afx.MultiplyVolume(musica_volumen),
                    afx.AudioFadeIn(1.0),
                    afx.AudioFadeOut(1.0),
                ])
            )
            audio_final = CompositeAudioClip([audio, musica])
            logger.info("Música de fondo mezclada (volumen relativo %.0f%%).", musica_volumen * 100)
        except Exception as exc:  # noqa: BLE001 - la música es un extra, no debe tumbar el video
            logger.warning("No se pudo mezclar la música de fondo, se sigue sin ella: %s", exc)

    video_con_audio = video_con_capas.with_audio(audio_final)

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
    final.write_videofile(
        str(salida),
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        logger=None,
        # "veryfast" a propósito: usa buffers de look-ahead más chicos que el
        # default de ffmpeg (menos RAM durante el encode), además de ser más
        # rápido — para reels de 60-90s la pérdida de compresión es despreciable.
        preset=video_cfg.get("preset", "veryfast"),
        threads=video_cfg.get("threads", 2),
    )
    logger.info("Video final escrito en %s (%.1fs).", salida, final.duration)
    return salida
