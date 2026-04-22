from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar


@dataclass
class FrameProgress:
    frame: int
    current_sample: int | None = None
    total_samples: int | None = None
    memory_mb: float | None = None
    peak_memory_mb: float | None = None
    elapsed: str | None = None
    status: str = ""


class ProgressParser:
    FRA_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"Fra:(\d+)\s+Mem:([\d.]+)M\s+\(Peak\s+([\d.]+)M\)\s+\|\s+Time:([\d:.]+)\s+\|\s+(.*)"
    )
    SAMPLE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"Rendering\s+(\d+)\s*/\s*(\d+)\s+samples"
    )
    SAVED_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"Saved:\s+'(.+?)'"
    )

    def __init__(self) -> None:
        self._current_frame: int = 0
        self._current_sample: int | None = None
        self._total_samples: int | None = None

    def parse_line(self, line: str) -> FrameProgress | Path | None:
        saved = self.SAVED_PATTERN.search(line)
        if saved:
            return Path(saved.group(1))

        fra = self.FRA_PATTERN.search(line)
        if fra:
            self._current_frame = int(fra.group(1))
            progress = FrameProgress(
                frame=self._current_frame,
                memory_mb=float(fra.group(2)),
                peak_memory_mb=float(fra.group(3)),
                elapsed=fra.group(4),
                status=fra.group(5).strip(),
            )
            sample = self.SAMPLE_PATTERN.search(fra.group(5))
            if sample:
                progress.current_sample = int(sample.group(1))
                progress.total_samples = int(sample.group(2))
                self._current_sample = progress.current_sample
                self._total_samples = progress.total_samples
            return progress

        sample = self.SAMPLE_PATTERN.search(line)
        if sample:
            self._current_sample = int(sample.group(1))
            self._total_samples = int(sample.group(2))
            return FrameProgress(
                frame=self._current_frame,
                current_sample=self._current_sample,
                total_samples=self._total_samples,
            )

        return None
