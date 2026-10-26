"""Cheap performance numbers per session: cold start time, frame rendering, memory.

Not a profiler: enough to notice "this build starts slower / janks more / uses more memory" between runs.
Results go into the active session's session.json under "performance".
"""

from __future__ import annotations

import json
import re
import shlex
import statistics
from pathlib import Path

from ..core import session, state
from .adb import Adb, AdbError


def parse_am_start(output: str) -> dict:
    """`am start -W` -> {"total_ms", "wait_ms", "launch_state"}."""
    out = {}
    if m := re.search(r"TotalTime:\s*(\d+)", output):
        out["total_ms"] = int(m.group(1))
    if m := re.search(r"WaitTime:\s*(\d+)", output):
        out["wait_ms"] = int(m.group(1))
    if m := re.search(r"LaunchState:\s*(\w+)", output):
        out["launch_state"] = m.group(1)
    return out


def parse_gfxinfo(output: str) -> dict:
    """`dumpsys gfxinfo <pkg>` -> frames, janky frames and frame-time percentiles."""
    out: dict = {}
    if m := re.search(r"Total frames rendered:\s*(\d+)", output):
        out["frames"] = int(m.group(1))
    if m := re.search(r"^Janky frames:\s*(\d+)\s*\(([\d.]+)%\)", output, re.M):
        out["janky"], out["janky_pct"] = int(m.group(1)), float(m.group(2))
    for pct in (50, 90, 95, 99):
        if m := re.search(rf"^{pct}th percentile:\s*(\d+)ms", output, re.M):
            out[f"p{pct}_ms"] = int(m.group(1))
    return out


def parse_meminfo(output: str) -> dict:
    """`dumpsys meminfo <pkg>` -> {"pss_kb", "rss_kb"}."""
    out = {}
    if m := re.search(r"TOTAL PSS:\s*([\d,]+)", output):
        out["pss_kb"] = int(m.group(1).replace(",", ""))
    elif m := re.search(r"^\s*TOTAL\s+(\d+)", output, re.M):
        out["pss_kb"] = int(m.group(1))
    if m := re.search(r"TOTAL RSS:\s*([\d,]+)", output):
        out["rss_kb"] = int(m.group(1).replace(",", ""))
    return out


def launcher_component(adb: Adb, package: str) -> str:
    out = adb.shell(f"cmd package resolve-activity --brief -c android.intent.category.LAUNCHER {shlex.quote(package)}",
                    check=False)
    component = out.strip().splitlines()[-1].strip() if out.strip() else ""
    if "/" not in component:
        raise AdbError(f"no launcher activity found for {package}")
    return component


def startup(adb: Adb, package: str, runs: int = 3) -> dict:
    """Cold starts: force-stop, then launch and wait for the first frame. Median of `runs`."""
    component = launcher_component(adb, package)
    samples = []
    for _ in range(runs):
        adb.shell("am", "force-stop", package)
        result = parse_am_start(adb.shell("am", "start", "-W", "-n", component, timeout=60))
        if "total_ms" in result:
            samples.append(result["total_ms"])
    if not samples:
        raise AdbError("am start -W reported no TotalTime")
    return {"cold_start_ms": round(statistics.median(samples)), "samples_ms": samples}


def frames(adb: Adb, package: str, reset: bool = False) -> dict:
    """Frame stats since the last reset (reset at session start, read at wrap-up)."""
    if reset:
        adb.shell("dumpsys", "gfxinfo", package, "reset", check=False)
        return {"reset": True}
    return parse_gfxinfo(adb.shell("dumpsys", "gfxinfo", package))


_OBJECTS = {"Activities": "activities", "ViewRootImpl": "view_roots", "AppContexts": "app_contexts",
            "Views": "views", "WebViews": "webviews"}


def parse_objects(output: str) -> dict:
    """The 'Objects' section of `dumpsys meminfo <pkg>`: live Activities, windows, contexts, Views, WebViews.

    Without the app's source these are the clearest leak signal: an Activity count that keeps growing
    while the user returns to the same screen means screens are kept alive after they close.
    """
    return {key: int(m.group(1)) for name, key in _OBJECTS.items()
            if (m := re.search(rf"\b{name}:\s+(\d+)", output))}


def memory(adb: Adb, package: str) -> dict:
    out = adb.shell("dumpsys", "meminfo", package, timeout=30)
    return {**parse_meminfo(out), **parse_objects(out)}


# Growth across cycles that counts as a suspected leak. Counts must never go down; PSS may wobble a little.
_LEAK_COUNTS = {"activities": 2, "view_roots": 2, "app_contexts": 2, "webviews": 2, "views": 100}
_PSS_GROWTH = (0.10, 8 * 1024)  # at least 10% and 8 MB from the first cycle to the last
_PSS_WOBBLE = 0.02              # a drop of up to 2% between cycles still counts as steady growth


def leak_verdict(samples: list[dict]) -> dict:
    """Compare memory after each repetition of the same flow (first sample = baseline before the cycles)."""
    if len(samples) < 4:
        return {"verdict": "not enough cycles", "cycles": max(0, len(samples) - 1), "growing": {}}
    growing = {}
    for key, minimum in _LEAK_COUNTS.items():
        values = [s[key] for s in samples if key in s]
        if len(values) == len(samples) and all(b >= a for a, b in zip(values, values[1:], strict=False)) \
                and values[-1] - values[0] >= minimum:
            growing[key] = values
    pss = [s["pss_kb"] for s in samples if "pss_kb" in s]
    if len(pss) == len(samples):
        steady = all(b >= a * (1 - _PSS_WOBBLE) for a, b in zip(pss, pss[1:], strict=False))
        grown = pss[-1] - pss[0]
        if steady and grown >= _PSS_GROWTH[0] * pss[0] and grown >= _PSS_GROWTH[1]:
            growing["pss_kb"] = pss
    return {"verdict": "suspected leak" if growing else "no leak seen", "cycles": len(samples) - 1,
            "growing": growing}


def append(serial: str, key: str, value: dict) -> Path | None:
    """Add a sample to the list at performance.<key> in the active session's session.json."""
    run = session.run_dir(serial)
    if run is None:
        return None
    path = run / "session.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("performance", {}).setdefault(key, []).append(value)
    state.write_json(path, data)
    return path


def record(serial: str, key: str, values: dict) -> Path | None:
    """Store a measurement in the active session's session.json under performance.<key>."""
    run = session.run_dir(serial)
    if run is None:
        return None
    path = run / "session.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("performance", {})[key] = values
    state.write_json(path, data)
    return path
