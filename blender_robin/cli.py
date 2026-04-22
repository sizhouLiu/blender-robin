from __future__ import annotations

from pathlib import Path

import click

from .batch import BatchProcessor
from .config import RenderConfig, load_configs_from_toml, parse_frame_range
from .discovery import BlenderNotFoundError, discover_blender, get_blender_version
from .progress import FrameProgress
from .queue import JobStatus, RenderQueue
from .renderer import BlenderRenderer
from .worker import QueueWorker


def _print_progress(p: FrameProgress) -> None:
    parts = [f"Frame {p.frame}"]
    if p.current_sample and p.total_samples:
        parts.append(f"Sample {p.current_sample}/{p.total_samples}")
    if p.memory_mb:
        parts.append(f"Mem {p.memory_mb:.0f}MB")
    if p.elapsed:
        parts.append(f"Time {p.elapsed}")
    if p.status:
        parts.append(p.status)
    click.echo(f"\r  {' | '.join(parts)}", nl=False)


@click.group()
@click.option("--blender", envvar="BLENDER_PATH", type=click.Path(), default=None,
              help="Path to Blender executable. Also reads BLENDER_PATH env var.")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output.")
@click.pass_context
def cli(ctx: click.Context, blender: str | None, verbose: bool) -> None:
    """robin - Blender rendering toolkit."""
    ctx.ensure_object(dict)
    ctx.obj["blender_override"] = blender
    ctx.obj["verbose"] = verbose


def _get_renderer(ctx: click.Context, with_progress: bool = True) -> BlenderRenderer:
    override = ctx.obj.get("blender_override")
    if override:
        blender_path = Path(override)
    else:
        try:
            blender_path = discover_blender()
        except BlenderNotFoundError as e:
            raise click.ClickException(str(e))
    callback = _print_progress if with_progress else None
    return BlenderRenderer(blender_path, progress_callback=callback)


# ── render ──────────────────────────────────────────────────────────────

@cli.command()
@click.argument("blend_file", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default="./output", help="Output directory.")
@click.option("--format", "-F", "output_format", default="PNG",
              type=click.Choice(["PNG", "JPEG", "EXR", "OPEN_EXR", "TIFF", "BMP"], case_sensitive=False))
@click.option("--resolution", "-r", nargs=2, type=int, default=(1920, 1080), help="Width Height.")
@click.option("--engine", "-e", default="CYCLES",
              type=click.Choice(["CYCLES", "BLENDER_EEVEE_NEXT", "WORKBENCH"], case_sensitive=False))
@click.option("--frames", "-f", default="1", help="Frame range: '1', '1-250', '1-250x2'.")
@click.option("--samples", "-s", type=int, default=None, help="Override sample count.")
@click.option("--scene", default=None, help="Scene name (default: active scene).")
@click.option("--device", type=click.Choice(["GPU", "CPU"], case_sensitive=False), default="GPU")
@click.option("--use-script", is_flag=True, help="Use Python script mode for complex overrides.")
@click.option("--dry-run", is_flag=True, help="Print the Blender command without executing.")
@click.pass_context
def render(ctx: click.Context, blend_file: str, output: str, output_format: str,
           resolution: tuple[int, int], engine: str, frames: str, samples: int | None,
           scene: str | None, device: str, use_script: bool, dry_run: bool) -> None:
    """Render a single .blend file."""
    start, end, step = parse_frame_range(frames)
    config = RenderConfig(
        blend_file=Path(blend_file),
        output_dir=Path(output),
        output_format=output_format.upper(),
        resolution_x=resolution[0],
        resolution_y=resolution[1],
        engine=engine.upper(),
        device=device.upper(),
        samples=samples,
        frame_start=start,
        frame_end=end,
        frame_step=step,
        scene=scene,
        use_script=use_script,
    )

    renderer = _get_renderer(ctx)

    if dry_run:
        cmd = renderer.build_command(config)
        click.echo(" ".join(cmd))
        return

    click.echo(f"Rendering {blend_file} (frames {start}-{end})...")
    result = renderer.render(config)
    click.echo()

    if result.success:
        click.echo(f"Done. {result.frame_count} frame(s) in {result.elapsed_seconds:.1f}s")
        for f in result.output_files:
            click.echo(f"  {f}")
    else:
        click.echo(f"Failed (exit code {result.return_code})")
        if result.error_message:
            click.echo(result.error_message)
        raise SystemExit(1)


# ── batch ───────────────────────────────────────────────────────────────

@cli.command()
@click.argument("directory", required=False, type=click.Path(exists=True))
@click.option("--config", "-c", "config_file", type=click.Path(exists=True), help="TOML config file.")
@click.option("--pattern", default="*.blend", help="Glob pattern for .blend files.")
@click.option("--parallel", "-j", default=1, type=int, help="Max parallel renders.")
@click.option("--output", "-o", type=click.Path(), default="./output", help="Output directory.")
@click.option("--engine", "-e", default="CYCLES")
@click.option("--dry-run", is_flag=True, help="Print what would be rendered.")
@click.pass_context
def batch(ctx: click.Context, directory: str | None, config_file: str | None,
          pattern: str, parallel: int, output: str, engine: str, dry_run: bool) -> None:
    """Batch render multiple .blend files."""
    if config_file:
        configs = load_configs_from_toml(Path(config_file))
    elif directory:
        configs = BatchProcessor.from_directory(
            Path(directory), None, pattern=pattern,
            output_dir=Path(output), engine=engine,
        )
    else:
        raise click.UsageError("Provide a DIRECTORY or --config file.")

    if not configs:
        click.echo("No .blend files found.")
        return

    renderer = _get_renderer(ctx)

    if dry_run:
        for cfg in configs:
            cmd = renderer.build_command(cfg)
            click.echo(" ".join(cmd))
        return

    click.echo(f"Batch rendering {len(configs)} file(s) (parallel={parallel})...")
    processor = BatchProcessor(renderer, max_parallel=parallel)
    result = processor.process(configs)
    click.echo()
    click.echo(
        f"Done. {result.succeeded}/{result.total} succeeded, "
        f"{result.failed} failed, {result.elapsed_seconds:.1f}s total"
    )
    for r in result.results:
        status = "OK" if r.success else "FAIL"
        click.echo(f"  [{status}] {r.blend_file.name} ({r.frame_count} frames, {r.elapsed_seconds:.1f}s)")


# ── uv-check ───────────────────────────────────────────────────────────

@cli.command("uv-check")
@click.argument("directory", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default="./uv_check_output", help="Output directory.")
@click.option("--resolution", "-r", nargs=2, type=int, default=(1920, 1080), help="Width Height.")
@click.option("--style", type=click.Choice(["color_grid", "checker"], case_sensitive=False),
              default="color_grid", help="UV checker pattern style.")
@click.option("--scale", type=float, default=8.0, help="Checker scale (only for 'checker' style).")
@click.option("--pattern", default="*.glb", help="Glob pattern for model files.")
@click.option("--parallel", "-j", default=1, type=int, help="Max parallel renders.")
@click.option("--dry-run", is_flag=True, help="Print commands without executing.")
@click.pass_context
def uv_check(ctx: click.Context, directory: str, output: str, resolution: tuple[int, int],
             style: str, scale: float, pattern: str, parallel: int, dry_run: bool) -> None:
    """Render UV checker maps for all GLB/GLTF files in a directory."""
    output_dir = Path(output)
    dir_path = Path(directory)

    # Discover GLB/GLTF files
    model_files = sorted(dir_path.glob(pattern))
    if not model_files:
        click.echo(f"No files matching '{pattern}' found in {directory}")
        return

    configs = []
    for model_file in model_files:
        cfg = RenderConfig(
            blend_file=model_file,
            output_dir=output_dir,
            engine="BLENDER_EEVEE_NEXT",
            resolution_x=resolution[0],
            resolution_y=resolution[1],
            use_script=True,
            script_name="uv_checker_glb.py",
            filename_pattern=model_file.stem,
            script_options={"style": style, "scale": scale},
        )
        # Pass GLB file path through config
        cfg.script_options["glb_file"] = str(model_file)
        configs.append(cfg)

    renderer = _get_renderer(ctx, with_progress=False)

    if dry_run:
        for cfg in configs:
            cmd = renderer.build_command(cfg)
            click.echo(" ".join(cmd))
        return

    click.echo(f"UV check rendering {len(configs)} file(s) (style={style})...")
    processor = BatchProcessor(renderer, max_parallel=parallel)
    result = processor.process(configs)
    click.echo()
    click.echo(
        f"Done. {result.succeeded}/{result.total} succeeded, "
        f"{result.failed} failed, {result.elapsed_seconds:.1f}s total"
    )
    for r in result.results:
        status = "OK" if r.success else "FAIL"
        click.echo(f"  [{status}] {r.blend_file.name}")


# ── rgb-closeup ─────────────────────────────────────────────────────────

@cli.command("rgb-closeup")
@click.argument("directory", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default="./rgb_output", help="Output directory.")
@click.option("--resolution", "-r", nargs=2, type=int, default=(1920, 1080), help="Width Height.")
@click.option("--pattern", default="*.glb", help="Glob pattern for model files.")
@click.option("--parallel", "-j", default=1, type=int, help="Max parallel renders.")
@click.option("--dry-run", is_flag=True, help="Print commands without executing.")
@click.pass_context
def rgb_closeup(ctx: click.Context, directory: str, output: str, resolution: tuple[int, int],
                pattern: str, parallel: int, dry_run: bool) -> None:
    """Render RGB full-body + random closeup for all GLB/GLTF files."""
    output_dir = Path(output)
    dir_path = Path(directory)

    model_files = sorted(dir_path.glob(pattern))
    if not model_files:
        click.echo(f"No files matching '{pattern}' found in {directory}")
        return

    configs = []
    for model_file in model_files:
        cfg = RenderConfig(
            blend_file=model_file,
            output_dir=output_dir,
            engine="BLENDER_EEVEE_NEXT",
            resolution_x=resolution[0],
            resolution_y=resolution[1],
            use_script=True,
            script_name="rgb_closeup.py",
            filename_pattern=model_file.stem,
            script_options={"glb_file": str(model_file)},
        )
        configs.append(cfg)

    renderer = _get_renderer(ctx, with_progress=False)

    if dry_run:
        for cfg in configs:
            cmd = renderer.build_command(cfg)
            click.echo(" ".join(cmd))
        return

    click.echo(f"RGB closeup rendering {len(configs)} file(s)...")
    processor = BatchProcessor(renderer, max_parallel=parallel)
    result = processor.process(configs)
    click.echo()
    click.echo(
        f"Done. {result.succeeded}/{result.total} succeeded, "
        f"{result.failed} failed, {result.elapsed_seconds:.1f}s total"
    )
    for r in result.results:
        status = "OK" if r.success else "FAIL"
        click.echo(f"  [{status}] {r.blend_file.name}")


# ── wireframe ───────────────────────────────────────────────────────────

@cli.command("wireframe")
@click.argument("directory", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default="./wireframe_output", help="Output directory.")
@click.option("--resolution", "-r", nargs=2, type=int, default=(1920, 1080), help="Width Height.")
@click.option("--wire-size", type=float, default=1.5, help="Wireframe line thickness in pixels.")
@click.option("--pattern", default="*.glb", help="Glob pattern for model files.")
@click.option("--parallel", "-j", default=1, type=int, help="Max parallel renders.")
@click.option("--dry-run", is_flag=True, help="Print commands without executing.")
@click.pass_context
def wireframe(ctx: click.Context, directory: str, output: str, resolution: tuple[int, int],
              wire_size: float, pattern: str, parallel: int, dry_run: bool) -> None:
    """Render wireframe-on-white for all GLB/GLTF files."""
    output_dir = Path(output)
    dir_path = Path(directory)

    model_files = sorted(dir_path.glob(pattern))
    if not model_files:
        click.echo(f"No files matching '{pattern}' found in {directory}")
        return

    configs = []
    for model_file in model_files:
        cfg = RenderConfig(
            blend_file=model_file,
            output_dir=output_dir,
            engine="BLENDER_EEVEE_NEXT",
            resolution_x=resolution[0],
            resolution_y=resolution[1],
            use_script=True,
            script_name="wireframe.py",
            filename_pattern=model_file.stem,
            script_options={"glb_file": str(model_file), "wire_size": wire_size},
        )
        configs.append(cfg)

    renderer = _get_renderer(ctx, with_progress=False)

    if dry_run:
        for cfg in configs:
            cmd = renderer.build_command(cfg)
            click.echo(" ".join(cmd))
        return

    click.echo(f"Wireframe rendering {len(configs)} file(s)...")
    processor = BatchProcessor(renderer, max_parallel=parallel)
    result = processor.process(configs)
    click.echo()
    click.echo(
        f"Done. {result.succeeded}/{result.total} succeeded, "
        f"{result.failed} failed, {result.elapsed_seconds:.1f}s total"
    )
    for r in result.results:
        status = "OK" if r.success else "FAIL"
        click.echo(f"  [{status}] {r.blend_file.name}")


# ── queue ───────────────────────────────────────────────────────────────

@cli.group()
@click.option("--db", type=click.Path(), default="render_queue.db", help="Queue database path.")
@click.pass_context
def queue(ctx: click.Context, db: str) -> None:
    """Manage the render queue."""
    ctx.obj["queue"] = RenderQueue(Path(db))


@queue.command("add")
@click.argument("blend_file", required=False, type=click.Path(exists=True))
@click.option("--config", "-c", "config_file", type=click.Path(exists=True), help="TOML config file.")
@click.option("--priority", "-p", default=0, type=int, help="Job priority (higher = first).")
@click.option("--output", "-o", type=click.Path(), default="./output")
@click.option("--engine", "-e", default="CYCLES")
@click.option("--frames", "-f", default="1")
@click.option("--samples", "-s", type=int, default=None)
@click.pass_context
def queue_add(ctx: click.Context, blend_file: str | None, config_file: str | None,
              priority: int, output: str, engine: str, frames: str, samples: int | None) -> None:
    """Add render job(s) to the queue."""
    q: RenderQueue = ctx.obj["queue"]

    if config_file:
        configs = load_configs_from_toml(Path(config_file))
        ids = q.add_batch(configs, priority=priority)
        click.echo(f"Added {len(ids)} job(s): {ids}")
    elif blend_file:
        start, end, step = parse_frame_range(frames)
        config = RenderConfig(
            blend_file=Path(blend_file),
            output_dir=Path(output),
            engine=engine,
            samples=samples,
            frame_start=start,
            frame_end=end,
            frame_step=step,
        )
        job_id = q.add(config, priority=priority)
        click.echo(f"Added job #{job_id}")
    else:
        raise click.UsageError("Provide a BLEND_FILE or --config file.")


@queue.command("list")
@click.option("--status", "-s", type=click.Choice([s.value for s in JobStatus], case_sensitive=False),
              default=None, help="Filter by status.")
@click.pass_context
def queue_list(ctx: click.Context, status: str | None) -> None:
    """List jobs in the queue."""
    q: RenderQueue = ctx.obj["queue"]
    job_status = JobStatus(status) if status else None
    jobs = q.list_jobs(job_status)

    if not jobs:
        click.echo("No jobs found.")
        return

    click.echo(f"{'ID':>4}  {'Status':<10}  {'Pri':>3}  {'File'}")
    click.echo("-" * 60)
    for job in jobs:
        click.echo(f"{job.id:>4}  {job.status.value:<10}  {job.priority:>3}  {job.config.blend_file.name}")


@queue.command("run")
@click.option("--max-jobs", "-n", type=int, default=None, help="Max jobs to process (default: all).")
@click.pass_context
def queue_run(ctx: click.Context, max_jobs: int | None) -> None:
    """Start processing the render queue."""
    q: RenderQueue = ctx.obj["queue"]
    renderer = _get_renderer(ctx)
    worker = QueueWorker(q, renderer)

    stats = q.stats()
    pending = stats.get("pending", 0)
    if pending == 0:
        click.echo("No pending jobs.")
        return

    limit_str = f" (max {max_jobs})" if max_jobs else ""
    click.echo(f"Processing {pending} pending job(s){limit_str}... (Ctrl+C to stop)")
    worker.run(max_jobs=max_jobs)
    click.echo("\nQueue processing finished.")

    final_stats = q.stats()
    for s, count in final_stats.items():
        click.echo(f"  {s}: {count}")


@queue.command("cancel")
@click.argument("job_id", type=int)
@click.pass_context
def queue_cancel(ctx: click.Context, job_id: int) -> None:
    """Cancel a pending or running job."""
    q: RenderQueue = ctx.obj["queue"]
    q.cancel(job_id)
    click.echo(f"Cancelled job #{job_id}")


@queue.command("retry")
@click.argument("job_id", required=False, type=int)
@click.option("--all-failed", is_flag=True, help="Retry all failed jobs.")
@click.pass_context
def queue_retry(ctx: click.Context, job_id: int | None, all_failed: bool) -> None:
    """Retry a failed job or all failed jobs."""
    q: RenderQueue = ctx.obj["queue"]
    if all_failed:
        jobs = q.list_jobs(JobStatus.FAILED)
        for job in jobs:
            q.retry(job.id)
        click.echo(f"Retried {len(jobs)} failed job(s)")
    elif job_id is not None:
        q.retry(job_id)
        click.echo(f"Retried job #{job_id}")
    else:
        raise click.UsageError("Provide a JOB_ID or --all-failed.")


@queue.command("clear")
@click.option("--status", "-s", type=click.Choice([s.value for s in JobStatus], case_sensitive=False),
              default=None, help="Only clear jobs with this status.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
@click.pass_context
def queue_clear(ctx: click.Context, status: str | None, yes: bool) -> None:
    """Clear jobs from the queue."""
    q: RenderQueue = ctx.obj["queue"]
    label = f"all {status} jobs" if status else "ALL jobs"
    if not yes:
        click.confirm(f"Remove {label}?", abort=True)
    job_status = JobStatus(status) if status else None
    count = q.clear(job_status)
    click.echo(f"Removed {count} job(s)")


@queue.command("stats")
@click.pass_context
def queue_stats(ctx: click.Context) -> None:
    """Show queue statistics."""
    q: RenderQueue = ctx.obj["queue"]
    stats = q.stats()
    if not stats:
        click.echo("Queue is empty.")
        return
    total = sum(stats.values())
    click.echo(f"Total: {total}")
    for s, count in stats.items():
        click.echo(f"  {s}: {count}")


# ── config ──────────────────────────────────────────────────────────────

@cli.group("config")
def config_group() -> None:
    """Blender configuration and diagnostics."""
    pass


@config_group.command("check")
@click.option("--blender", envvar="BLENDER_PATH", type=click.Path(), default=None)
def config_check(blender: str | None) -> None:
    """Verify Blender is found and runnable."""
    if blender:
        blender_path = Path(blender)
    else:
        try:
            blender_path = discover_blender()
        except BlenderNotFoundError as e:
            raise click.ClickException(str(e))

    click.echo(f"Blender path: {blender_path}")
    version = get_blender_version(blender_path)
    click.echo(f"Blender version: {version}")
    click.echo("OK")


@config_group.command("show")
@click.option("--blender", envvar="BLENDER_PATH", type=click.Path(), default=None)
def config_show(blender: str | None) -> None:
    """Show resolved configuration."""
    if blender:
        blender_path = Path(blender)
    else:
        try:
            blender_path = discover_blender()
        except BlenderNotFoundError:
            blender_path = None

    click.echo(f"Blender: {blender_path or 'NOT FOUND'}")
    if blender_path:
        click.echo(f"Version: {get_blender_version(blender_path)}")

    defaults = RenderConfig(blend_file=Path("example.blend"))
    click.echo(f"Default engine: {defaults.engine}")
    click.echo(f"Default device: {defaults.device}")
    click.echo(f"Default resolution: {defaults.resolution_x}x{defaults.resolution_y}")
    click.echo(f"Default format: {defaults.output_format}")
