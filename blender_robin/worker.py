from __future__ import annotations

import signal
import sys

from .queue import RenderQueue
from .renderer import BlenderRenderer


class QueueWorker:
    def __init__(self, queue: RenderQueue, renderer: BlenderRenderer) -> None:
        self.queue = queue
        self.renderer = renderer
        self._stop_requested = False

    def run(self, max_jobs: int | None = None) -> None:
        signal.signal(signal.SIGINT, self._handle_signal)
        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, self._handle_signal)

        processed = 0
        while not self._stop_requested:
            if max_jobs is not None and processed >= max_jobs:
                break

            job = self.queue.next_pending()
            if not job:
                break

            try:
                result = self.renderer.render(job.config)
                if result.success:
                    self.queue.complete(job.id, result)
                else:
                    self.queue.fail(job.id, result.error_message or "Render failed")
            except Exception as e:
                self.queue.fail(job.id, str(e))

            processed += 1

    def stop(self) -> None:
        self._stop_requested = True

    def _handle_signal(self, signum, frame) -> None:
        self.stop()
