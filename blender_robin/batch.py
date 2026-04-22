from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .config import RenderConfig
from .renderer import BlenderRenderer, RenderResult


@dataclass
class BatchResult:
    total: int
    succeeded: int
    failed: int
    results: list[RenderResult]
    elapsed_seconds: float


class BatchProcessor:
    def __init__(self, renderer: BlenderRenderer, max_parallel: int = 1) -> None:
        self.renderer = renderer
        self.max_parallel = max_parallel

    def process(self, configs: list[RenderConfig]) -> BatchResult:
        start = time.monotonic()
        results: list[RenderResult] = []

        if self.max_parallel == 1:
            for config in configs:
                result = self.renderer.render(config)
                results.append(result)
        else:
            with ProcessPoolExecutor(max_workers=self.max_parallel) as executor:
                futures = {executor.submit(self.renderer.render, cfg): cfg for cfg in configs}
                for future in as_completed(futures):
                    results.append(future.result())

        elapsed = time.monotonic() - start
        succeeded = sum(1 for r in results if r.success)
        failed = len(results) - succeeded

        return BatchResult(
            total=len(results),
            succeeded=succeeded,
            failed=failed,
            results=results,
            elapsed_seconds=elapsed,
        )

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        renderer: BlenderRenderer,
        pattern: str = "*.blend",
        **render_kwargs,
    ) -> list[RenderConfig]:
        configs: list[RenderConfig] = []
        for blend_file in sorted(directory.glob(pattern)):
            config = RenderConfig(blend_file=blend_file, **render_kwargs)
            configs.append(config)
        return configs
