from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


class BlenderNotFoundError(Exception):
    pass


def discover_blender() -> Path:
    """Find the Blender executable using multiple strategies."""
    env = os.environ.get("BLENDER_PATH")
    if env:
        p = Path(env.strip('"').strip("'"))
        if p.is_file():
            return p
        exe = p / "blender.exe" if p.is_dir() else None
        if exe and exe.is_file():
            return exe

    which = shutil.which("blender")
    if which:
        return Path(which)

    if sys.platform == "win32":
        found = _search_windows()
        if found:
            return found

    raise BlenderNotFoundError(
        "Could not find Blender. Tried:\n"
        "  1. BLENDER_PATH environment variable\n"
        "  2. System PATH lookup\n"
        "  3. Windows registry & common install directories\n\n"
        "Set BLENDER_PATH or pass --blender to the CLI."
    )


def _search_windows() -> Path | None:
    path = _check_registry()
    if path:
        return path

    candidates: list[Path] = []
    for base in [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    ]:
        for d in sorted(base.glob("Blender Foundation/Blender *"), reverse=True):
            exe = d / "blender.exe"
            if exe.is_file():
                candidates.append(exe)

    steam = Path(
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        "Steam", "steamapps", "common", "Blender", "blender.exe",
    )
    if steam.is_file():
        candidates.append(steam)

    local = Path(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "blender.exe")
    if local.is_file():
        candidates.append(local)

    return candidates[0] if candidates else None


def _check_registry() -> Path | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\BlenderFoundation") as key:
            install_dir, _ = winreg.QueryValueEx(key, "Install_Dir")
            exe = Path(install_dir) / "blender.exe"
            if exe.is_file():
                return exe
    except (OSError, ImportError):
        pass
    return None


def get_blender_version(blender_path: Path) -> str:
    """Run 'blender --version' and return the version string."""
    result = subprocess.run(
        [str(blender_path), "--version"],
        capture_output=True, text=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    for line in result.stdout.splitlines():
        m = re.search(r"Blender\s+(\d+\.\d+(?:\.\d+)?)", line)
        if m:
            return m.group(1)
    return "unknown"
