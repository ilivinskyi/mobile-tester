"""Finding an installed app by what a person calls it: its name ("Gmail") or its package id."""

from __future__ import annotations

import difflib
import re
import shlex
from dataclasses import dataclass

from ..core import state
from . import apkinfo
from .adb import Adb

_COMPONENT_RE = re.compile(r"^\s*([\w.]+)/[\w.$]+\s*$")


@dataclass
class Match:
    score: int
    package: str
    label: str
    version: str = ""

    def describe(self) -> str:
        return f"{self.label}  {self.package}  {self.version}".rstrip()


def parse_launcher_packages(query_activities_output: str) -> list[str]:
    """Packages from `cmd package query-activities --brief -a MAIN -c LAUNCHER`."""
    found = []
    for line in query_activities_output.splitlines():
        if (m := _COMPONENT_RE.match(line)) and m.group(1) not in found:
            found.append(m.group(1))
    return found


def launcher_packages(adb: Adb) -> list[str]:
    out = adb.shell("cmd package query-activities --brief -a android.intent.action.MAIN "
                    "-c android.intent.category.LAUNCHER", check=False, timeout=30)
    return parse_launcher_packages(out)


def _version_code(adb: Adb, package: str) -> str:
    out = adb.shell(f"dumpsys package {shlex.quote(package)} | grep -m1 versionCode=", check=False)
    m = re.search(r"versionCode=(\d+)", out)
    return m.group(1) if m else "?"


def base_apk(adb: Adb, package: str) -> str:
    """Path of the app's base APK on the device (`pm path` lists it first)."""
    out = adb.shell("pm", "path", package, check=False).splitlines()
    if not out or not out[0].startswith("package:"):
        raise LookupError(f"{package} is not installed")
    return out[0].removeprefix("package:").strip()


def manifest(adb: Adb, package: str) -> bytes:
    """The binary AndroidManifest.xml of an installed app, streamed from its APK (no full download)."""
    return adb.exec_out(f"unzip -p {shlex.quote(base_apk(adb, package))} AndroidManifest.xml")


def label(adb: Adb, package: str, locale: str = "") -> str:
    """The app's name as the launcher shows it, read from its APK on the device; cached per version.

    Only the manifest and resources.arsc are streamed (`unzip -p` on the device), not the whole APK.
    Falls back to the package name when the name can't be resolved.
    """
    cache_file = state.device_dir(adb.serial) / "labels.json"
    cache = state.read_json(cache_file) or {}
    key = f"{package}@{_version_code(adb, package)}:{locale}"
    if key in cache:
        return cache[key]
    name = package
    try:
        apk = base_apk(adb, package)
        found = apkinfo.application_label(adb.exec_out(f"unzip -p {shlex.quote(apk)} AndroidManifest.xml"))
        if isinstance(found, str) and found:
            name = found
        elif isinstance(found, apkinfo.ResourceRef):
            arsc = adb.exec_out(f"unzip -p {shlex.quote(apk)} resources.arsc", timeout=60)
            name = apkinfo.resource_string(arsc, found.res_id, locale) or package
    except Exception:  # noqa: BLE001 - any parsing or adb problem just means "show the package"
        name = package
    cache[key] = name
    state.write_json(cache_file, cache)
    return name


def _norm(text: str) -> str:
    return re.sub(r"[\s_\-]+", "", text.casefold())


def score(query: str, package: str, app_label: str) -> int:
    """How well a query matches an app: 100 exact, down to 0 for no match."""
    q, lab, pkg = _norm(query), _norm(app_label), package.casefold()
    if not q:
        return 0
    if q in (lab, pkg):
        return 100
    if lab.startswith(q):
        return 85
    if any(_norm(word).startswith(q) for word in app_label.split()):
        return 75
    if q in lab:
        return 65
    if q in pkg.split("."):
        return 70
    if q in pkg:
        return 55
    ratio = difflib.SequenceMatcher(None, q, lab).ratio()
    return round(50 * ratio) if ratio >= 0.75 else 0


def rank(query: str, apps: list[tuple[str, str]]) -> list[Match]:
    """apps: (package, label) pairs. Best match first; non-matches dropped."""
    matches = [Match(s, pkg, lab) for pkg, lab in apps if (s := score(query, pkg, lab)) > 0]
    return sorted(matches, key=lambda m: (-m.score, m.label.casefold()))


def find(adb: Adb, query: str, locale: str = "") -> list[Match]:
    query = query.strip()
    installed = set(adb.shell("pm", "list", "packages").replace("package:", "").split())
    if query in installed:
        # A package id: no need to read every label.
        return [Match(100, query, label(adb, query, locale))]
    packages = launcher_packages(adb)
    return rank(query, [(p, label(adb, p, locale)) for p in packages])
