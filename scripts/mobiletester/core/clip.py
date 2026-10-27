"""Recordings on a wall clock: timelines of recorded chunks, and clips cut by action-log times."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import state


class ClipError(Exception):
    pass


def duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    proc = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True)
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def build_timeline(chunks: list[tuple[float | None, float | None]]) -> list[dict]:
    """(wall start, measured duration) per chunk -> timeline entries.

    screenrecord only writes frames when the screen changes, so a chunk's measured duration ends at its
    last frame: a still screen at the end of a chunk would drop out of the joined video and make it run
    ahead of the clock. Each chunk therefore spans until the next one started (its wall-clock length);
    only the last chunk uses its measured duration.
    """
    timeline, video_pos = [], 0.0
    for i, (wall_start, duration) in enumerate(chunks):
        next_start = chunks[i + 1][0] if i + 1 < len(chunks) else None
        span = next_start - wall_start if wall_start is not None and next_start is not None else duration
        timeline.append({"wall_start": wall_start, "video_start": round(video_pos, 3), "duration": duration,
                         "span": round(span, 3) if span is not None else None})
        video_pos += span or 0.0
    return timeline


def video_position(timeline: dict, wall: float) -> float | None:
    """Seconds into the joined video for a wall-clock time, or None if it falls outside the recording."""
    for chunk in timeline["chunks"]:
        start = chunk["wall_start"]
        length = chunk.get("span") or chunk["duration"]  # older timelines have no span
        if start is None or length is None:
            return None
        if start <= wall <= start + length:
            return chunk["video_start"] + (wall - start)
    return None


def _last_frame_at(video: Path, position: float) -> float:
    """Time of the frame on screen at `position`: the last one at or before it (0 when none is found).

    A still screen has no frames of its own, so a clip starting there must begin from that earlier frame.
    """
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return position
    for lookback in (300.0, position):
        proc = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v", "-read_intervals",
                               f"{max(0.0, position - lookback):.3f}%{position + 0.001:.3f}",
                               "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(video)],
                              capture_output=True, text=True)
        times = [float(v) for v in proc.stdout.split() if v.replace(".", "", 1).isdigit()]
        if earlier := [v for v in times if v <= position + 0.001]:
            return max(earlier)
    return 0.0


def cut_clip(video: Path, wall_from: float, wall_to: float, out: Path, pad: float = 3.0) -> tuple[float, float]:
    """Cut [wall_from - pad, wall_to + pad] from a recording made by record_start, re-encoded at 540p.

    The clip runs at a constant 30 fps, each frame held until the next one: screenrecord writes frames only
    when the screen changes, and cutting just the frames that exist would drop still stretches at both ends.
    """
    timeline = state.read_json(video.with_suffix(".timeline.json"))
    if not timeline:
        raise ClipError(f"no timeline next to {video}; record it with `adt record` or `idt record`")
    starts = [video_position(timeline, wall_from - pad), video_position(timeline, wall_from)]
    ends = [video_position(timeline, wall_to + pad), video_position(timeline, wall_to)]
    start = next((s for s in starts if s is not None), None)
    end = next((e for e in ends if e is not None), None)
    if start is None or end is None or end <= start:
        raise ClipError("the requested time range is not inside the recording")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ClipError("ffmpeg is required to cut clips")
    out.parent.mkdir(parents=True, exist_ok=True)
    seek = min(_last_frame_at(video, start), start)
    length = end - start
    filters = (f"fps=30,tpad=stop_mode=clone:stop_duration={length + 1:.3f},"
               f"trim=start={start - seek:.3f}:duration={length:.3f},setpts=PTS-STARTPTS,scale=540:-2")
    proc = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{seek:.3f}", "-i", str(video),
                           "-vf", filters, "-c:v", "libx264", "-crf", "26", "-preset", "veryfast", "-an", str(out)],
                          capture_output=True)
    if proc.returncode != 0:
        raise ClipError(f"ffmpeg failed: {proc.stderr.decode(errors='replace')}")
    return start, end


def concat_listing(chunks: list[Path], spans: list[float | None]) -> str:
    """ffmpeg concat list; `duration` makes each chunk last its wall-clock span (the last frame holds)."""
    lines = []
    for chunk, span in zip(chunks, spans, strict=True):
        lines.append(f"file '{chunk.resolve().as_posix()}'")
        if span:
            lines.append(f"duration {span:.3f}")
    return "\n".join(lines) + "\n"
