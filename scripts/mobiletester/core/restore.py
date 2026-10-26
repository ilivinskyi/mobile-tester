"""Device settings changed for a test, with their original values, so they can always be put back.

The first change of a setting records what it was; later changes keep that original. `session end`,
`env --reset` and `net online` restore everything recorded and forget it.
"""

from __future__ import annotations

from . import state


def _file(serial: str):
    return state.device_dir(serial) / "restore.json"


def remember(serial: str, key: str, original: str | None) -> None:
    saved = state.read_json(_file(serial)) or {}
    if key not in saved:
        saved[key] = original
        state.write_json(_file(serial), saved)


def pending(serial: str) -> dict[str, str | None]:
    return state.read_json(_file(serial)) or {}


def forget(serial: str, keys: list[str] | None = None) -> None:
    saved = pending(serial)
    for key in keys if keys is not None else list(saved):
        saved.pop(key, None)
    state.write_json(_file(serial), saved)
