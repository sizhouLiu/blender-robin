from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self


def parse_frame_range(spec: str) -> tuple[int, int, int]:
    """Parse a frame range string like '1', '1-250', or '1-250x2'."""
    m = re.fullmatch(r"(\d+)(?:-(\d+)(?:x(\d+))?)?", spec.strip())
    if not m:
        raise ValueError(f"Invalid frame range: {spec!r}  (expected N, N-N, or N-NxN)")
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start
    step = int(m.group(3)) if m.group(3) else 1
    return start, end, step


@dataclass
class RenderConfig:
    blend_file: Path
    output_dir: Path = Path("./output")
    output_format: str = "PNG"
    filename_pattern: str = "frame_####"
    resolution_x: int = 1920
    resolution_y: int = 1080
    resolution_percentage: int = 100
    engine: str = "CYCLES"
    device: str = "GPU"
    samples: int | None = None
    frame_start: int = 1
    frame_end: int = 1
    frame_step: int = 1
    scene: str | None = None
    use_script: bool = False
    script_name: str = "render_setup.py"
    script_options: dict = field(default_factory=dict)
    extra_args: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        d: dict = {}
        d["blend_file"] = Path(data["blend_file"])
        if "output_dir" in data:
            d["output_dir"] = Path(data["output_dir"])
        for key in (
            "output_format", "filename_pattern", "resolution_x", "resolution_y",
            "resolution_percentage", "engine", "device", "samples", "scene",
            "use_script", "script_name", "script_options", "extra_args",
        ):
            if key in data:
                d[key] = data[key]
        if "frames" in data:
            d["frame_start"], d["frame_end"], d["frame_step"] = parse_frame_range(data["frames"])
        else:
            for key in ("frame_start", "frame_end", "frame_step"):
                if key in data:
                    d[key] = data[key]
        return cls(**d)

    @classmethod
    def from_toml(cls, path: Path) -> Self:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        if "render" in data:
            return cls._from_toml_render(data["render"])
        raise ValueError(f"TOML file must contain a [render] section: {path}")

    @classmethod
    def _from_toml_render(cls, section: dict) -> Self:
        flat: dict = {}
        flat["blend_file"] = section["blend_file"]
        for key in ("output_dir", "output_format", "filename_pattern", "scene", "use_script", "extra_args"):
            if key in section:
                flat[key] = section[key]
        if "resolution" in section:
            res = section["resolution"]
            if "x" in res:
                flat["resolution_x"] = res["x"]
            if "y" in res:
                flat["resolution_y"] = res["y"]
            if "percentage" in res:
                flat["resolution_percentage"] = res["percentage"]
        if "engine" in section:
            eng = section["engine"]
            if isinstance(eng, str):
                flat["engine"] = eng
            else:
                if "name" in eng:
                    flat["engine"] = eng["name"]
                if "device" in eng:
                    flat["device"] = eng["device"]
                if "samples" in eng:
                    flat["samples"] = eng["samples"]
        for key in ("samples", "device"):
            if key in section:
                flat[key] = section[key]
        if "frames" in section:
            fr = section["frames"]
            if isinstance(fr, str):
                flat["frames"] = fr
            else:
                for key in ("start", "end", "step"):
                    if key in fr:
                        flat[f"frame_{key}"] = fr[key]
        return cls.from_dict(flat)

    def to_dict(self) -> dict:
        d = {
            "blend_file": str(self.blend_file),
            "output_dir": str(self.output_dir),
            "output_format": self.output_format,
            "filename_pattern": self.filename_pattern,
            "resolution_x": self.resolution_x,
            "resolution_y": self.resolution_y,
            "resolution_percentage": self.resolution_percentage,
            "engine": self.engine,
            "device": self.device,
            "samples": self.samples,
            "frame_start": self.frame_start,
            "frame_end": self.frame_end,
            "frame_step": self.frame_step,
            "scene": self.scene,
            "use_script": self.use_script,
            "script_name": self.script_name,
            "extra_args": self.extra_args,
        }
        if self.script_options:
            d["script_options"] = self.script_options
        return d


def load_configs_from_toml(path: Path) -> list[RenderConfig]:
    with open(path, "rb") as f:
        data = tomllib.load(f)

    if "render" in data:
        return [RenderConfig._from_toml_render(data["render"])]

    defaults: dict = {}
    jobs_list: list[dict] = []

    if "batch" in data:
        defaults = data["batch"].get("defaults", {})
        jobs_list = data["batch"].get("jobs", [])
        if "output_dir" in data["batch"]:
            defaults.setdefault("output_dir", data["batch"]["output_dir"])
        if "output_format" in data["batch"]:
            defaults.setdefault("output_format", data["batch"]["output_format"])
    elif "queue" in data:
        jobs_list = data["queue"].get("jobs", [])

    configs: list[RenderConfig] = []
    for job in jobs_list:
        merged = {**defaults, **job}
        configs.append(RenderConfig.from_dict(merged))
    return configs
