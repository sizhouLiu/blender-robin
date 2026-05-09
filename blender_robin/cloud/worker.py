"""
Distributed rendering worker.
Pulls tasks from the queue, renders locally, and uploads results to storage.

Designed to run as a long-lived process on a server or inside a K8s pod.

Usage:
    python -m blender_robin.cloud.worker

Configuration (environment variables):
    ROBIN_STORAGE_*        object storage target (see storage.py)
    ROBIN_QUEUE_*          task queue (see queue.py)
    ROBIN_NOTIFY_*         notifications (see notify.py)
    ROBIN_BLENDER_PATH     path to blender executable (auto-detected if omitted)
    ROBIN_WORK_DIR         temp directory for downloads / renders (default: ./_work)
    ROBIN_POLL_TIMEOUT     queue poll timeout in seconds (default: 30)
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from blender_robin.cloud.notify import Notifier
from blender_robin.cloud.queue import TaskQueue
from blender_robin.cloud.storage import ObjectStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("robin.worker")


def find_blender() -> str:
    """Auto-detect Blender executable path."""
    path = os.environ.get("ROBIN_BLENDER_PATH")
    if path:
        return path

    candidates = [
        "blender",
        r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
        "/usr/local/bin/blender",
        "/usr/bin/blender",
        "/opt/blender/blender",
    ]
    for c in candidates:
        if shutil.which(c):
            return c
    raise FileNotFoundError("Blender not found — set ROBIN_BLENDER_PATH")


def run_blender(script: str, config: dict, work_dir: Path, blender_path: str) -> int:
    """Execute a Blender render script. Returns exit code."""
    import json

    config_json = json.dumps(config, ensure_ascii=False)
    cmd = [blender_path, "--background", "--python", script, "--", config_json]
    log.info("Running: %s", blender_path)
    proc = subprocess.run(cmd, cwd=str(work_dir))
    return proc.returncode


async def process_one_task(
    task: dict,
    store: ObjectStore,
    notifier: Notifier,
    work_dir: Path,
    blender_path: str,
) -> None:
    """Download input, render, upload output, notify."""
    task_id = task.get("task_id", str(time.time()))
    log.info("Processing task %s: %s", task_id, task.get("mode", "unknown"))

    task_work = work_dir / task_id
    task_work.mkdir(parents=True, exist_ok=True)

    try:
        # ── Download input files ──────────────────────────────────────────
        glb_key = task.get("glb_key")
        glb_local = task_work / "model.glb"
        if glb_key:
            store.download_file(glb_key, glb_local)
            log.info("Downloaded %s → %s", glb_key, glb_local)
        else:
            log.warning("No glb_key in task, assuming file is local")

        hdri_key = task.get("hdri_key")
        if hdri_key:
            hdri_local = task_work / "environment.exr"
            store.download_file(hdri_key, hdri_local)
            task["hdri_path"] = str(hdri_local)

        # ── Prepare config ────────────────────────────────────────────────
        output_dir = task_work / "output"
        output_dir.mkdir(exist_ok=True)

        config = {
            "engine": task.get("engine", "BLENDER_EEVEE_NEXT"),
            "resolution_x": task.get("resolution_x", 1920),
            "resolution_y": task.get("resolution_y", 1080),
            "resolution_percentage": task.get("resolution_percentage", 100),
            "output_format": task.get("output_format", "PNG"),
            "output_dir": str(output_dir),
            "filename_pattern": task.get("filename_pattern", "render"),
            "script_options": {
                "glb_file": str(glb_local),
                "views": task.get("views"),
                "closeup_count": task.get("closeup_count", 0),
                "hdri_path": task.get("hdri_path"),
                "env_texture": task.get("env_texture"),
                "export_metadata": task.get("export_metadata", False),
                "no_composite": task.get("no_composite", False),
                "flat_shading": task.get("flat_shading", False),
            },
        }

        # ── Render ────────────────────────────────────────────────────────
        mode = task.get("mode", "rgb")
        script_map = {
            "rgb": "render_views.py",
            "clay": "render_views.py",
            "wireframe": "wireframe.py",
            "normal-map": "normal_map.py",
            "albedo": "albedo.py",
        }
        script_name = script_map.get(mode, "render_views.py")
        script_path = Path(__file__).resolve().parent.parent / "blender_scripts" / script_name

        if mode == "clay":
            # Override material to be a flat grey clay
            config["script_options"]["override_material"] = True

        rc = run_blender(str(script_path), config, task_work, blender_path)
        if rc != 0:
            notifier.send(f"task {task_id} failed: blender exit code {rc}",
                          f"render {mode} failed")
            log.error("Blender exited with %d for task %s", rc, task_id)
            return

        # ── Upload results ────────────────────────────────────────────────
        remote_prefix = task.get("remote_prefix", f"renders/{task_id}")
        uploaded = store.upload_directory(output_dir, remote_prefix)
        log.info("Uploaded %d files to %s", len(uploaded), remote_prefix)

        # ── Notify ────────────────────────────────────────────────────────
        notifier.send(
            f"task {task_id} completed — {len(uploaded)} files → {remote_prefix}",
            f"render {mode} done",
        )
        log.info("Task %s complete, %d files uploaded", task_id, len(uploaded))

    except Exception as e:
        log.exception("Task %s failed: %s", task_id, e)
        notifier.send(f"task {task_id} failed: {e}", f"render {task.get('mode')} failed")

    finally:
        # Clean up
        shutil.rmtree(task_work, ignore_errors=True)


async def main_loop() -> None:
    queue = TaskQueue.from_env()
    store = ObjectStore.from_env()
    notifier = Notifier.from_env()
    blender_path = find_blender()
    poll_timeout = int(os.environ.get("ROBIN_POLL_TIMEOUT", "30"))
    work_dir = Path(os.environ.get("ROBIN_WORK_DIR", "./_work"))
    work_dir.mkdir(parents=True, exist_ok=True)

    log.info("Robin worker starting — blender=%s", blender_path)
    log.info("  queue backend: %s", type(queue).__name__)
    notifier.send("robin worker started", "worker up")

    while True:
        try:
            task = queue.pop(timeout=poll_timeout)
            if task is None:
                continue
            await process_one_task(task, store, notifier, work_dir, blender_path)
            # Acknowledge if the backend supports it
            stream_id = task.get("_stream_id")
            if stream_id:
                queue.ack(stream_id)
        except KeyboardInterrupt:
            log.info("Worker shutting down")
            notifier.send("robin worker stopped", "worker down")
            break
        except Exception:
            log.exception("Unexpected error in main loop, sleeping 5s")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main_loop())
