from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import RenderConfig
from .progress import FrameProgress, ProgressParser


@dataclass
class RenderResult:
    success: bool
    blend_file: Path
    output_files: list[Path] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    frame_count: int = 0
    error_message: str | None = None
    return_code: int = 0


class BlenderRenderer:
    def __init__(
        self,
        blender_path: Path,
        progress_callback: Callable[[FrameProgress], None] | None = None,
    ) -> None:
        self.blender_path = blender_path
        self.progress_callback = progress_callback

    def render(self, config: RenderConfig) -> RenderResult:
        config.output_dir.mkdir(parents=True, exist_ok=True)
        if config.use_script:
            return self._run_with_script(config)
        return self._run_direct(config)

    def build_command(self, config: RenderConfig) -> list[str]:
        if config.use_script:
            return self._build_script_command(config)
        return self._build_direct_command(config)

    def _build_direct_command(self, config: RenderConfig) -> list[str]:
        cmd = [
            str(self.blender_path),
            "--background",
            str(config.blend_file),
        ]
        if config.scene:
            cmd += ["--scene", config.scene]

        output_path = config.output_dir / config.filename_pattern
        cmd += ["--render-output", str(output_path)]
        cmd += ["--render-format", config.output_format]

        if config.engine:
            cmd += ["--engine", config.engine]

        if config.frame_start == config.frame_end:
            cmd += ["--render-frame", str(config.frame_start)]
        else:
            frame_spec = f"{config.frame_start}..{config.frame_end}"
            if config.frame_step > 1:
                frame_spec += f"..{config.frame_step}"
            cmd += ["--render-frame", frame_spec]

        cmd += config.extra_args
        return cmd

    def _build_script_command(self, config: RenderConfig) -> list[str]:
        script_path = Path(__file__).parent / "blender_scripts" / config.script_name
        cmd = [
            str(self.blender_path),
            "--background",
        ]

        # Always start with empty scene in script mode — the script imports the model
        # (opening .blend as main scene and then appending from it via libraries.load fails)

        cmd += [
            "--python", str(script_path),
            "--",
            json.dumps(config.to_dict()),
        ]
        return cmd

    def _run_direct(self, config: RenderConfig) -> RenderResult:
        cmd = self._build_direct_command(config)
        return self._execute(cmd, config)

    def _run_with_script(self, config: RenderConfig) -> RenderResult:
        cmd = self._build_script_command(config)
        return self._execute(cmd, config)

    def _execute(self, cmd: list[str], config: RenderConfig) -> RenderResult:
        parser = ProgressParser()
        output_files: list[Path] = []
        stderr_lines: list[str] = []
        start = time.monotonic()

        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            creationflags=creationflags,
        )

        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            result = parser.parse_line(line)
            if isinstance(result, Path):
                output_files.append(result)
            elif isinstance(result, FrameProgress) and self.progress_callback:
                self.progress_callback(result)

        assert proc.stderr is not None
        stderr_lines = proc.stderr.read().splitlines()
        proc.wait()
        elapsed = time.monotonic() - start

        success = proc.returncode == 0
        return RenderResult(
            success=success,
            blend_file=config.blend_file,
            output_files=output_files,
            elapsed_seconds=elapsed,
            frame_count=len(output_files),
            error_message="\n".join(stderr_lines) if not success else None,
            return_code=proc.returncode,
        )
