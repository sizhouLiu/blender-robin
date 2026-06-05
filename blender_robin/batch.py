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
        total = len(configs)

        if self.max_parallel == 1:
            for i, config in enumerate(configs, 1):
                print(f"  渲染 [{i}/{total}] {config.blend_file.name}", flush=True)
                result = self.renderer.render(config)
                results.append(result)
        else:
            with ProcessPoolExecutor(max_workers=self.max_parallel) as executor:
                futures = {executor.submit(self.renderer.render, cfg): cfg for cfg in configs}
                for i, future in enumerate(as_completed(futures), 1):
                    result = future.result()
                    status = "OK" if result.success else "FAIL"
                    print(f"  [{i}/{total}] [{status}] {result.blend_file.name}", flush=True)
                    results.append(result)

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
