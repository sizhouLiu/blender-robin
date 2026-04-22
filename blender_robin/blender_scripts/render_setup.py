"""
This script runs INSIDE Blender's Python interpreter.
Invoked via: blender --background file.blend --python render_setup.py -- <json_config>

Do NOT import this from the host Python environment.
"""
import json
import sys


def main() -> None:
    import bpy

    separator_idx = sys.argv.index("--")
    config_json = sys.argv[separator_idx + 1]
    config = json.loads(config_json)

    scene = bpy.context.scene
    if config.get("scene"):
        scene = bpy.data.scenes[config["scene"]]
        bpy.context.window.scene = scene

    render = scene.render

    render.resolution_x = config.get("resolution_x", render.resolution_x)
    render.resolution_y = config.get("resolution_y", render.resolution_y)
    render.resolution_percentage = config.get("resolution_percentage", render.resolution_percentage)

    engine = config.get("engine")
    if engine:
        render.engine = engine

    fmt = config.get("output_format")
    if fmt:
        render.image_settings.file_format = fmt

    output_dir = config.get("output_dir", "./output")
    filename_pattern = config.get("filename_pattern", "frame_####")
    render.filepath = f"{output_dir}/{filename_pattern}"

    samples = config.get("samples")
    if samples is not None:
        if render.engine == "CYCLES":
            scene.cycles.samples = samples
        elif render.engine == "BLENDER_EEVEE_NEXT":
            scene.eevee.taa_render_samples = samples

    device = config.get("device")
    if device and render.engine == "CYCLES":
        scene.cycles.device = device
        if device == "GPU":
            prefs = bpy.context.preferences.addons.get("cycles")
            if prefs:
                prefs.preferences.compute_device_type = "CUDA"
                for d in prefs.preferences.devices:
                    d.use = d.type != "CPU"

    frame_start = config.get("frame_start", scene.frame_start)
    frame_end = config.get("frame_end", scene.frame_end)
    frame_step = config.get("frame_step", 1)

    scene.frame_start = frame_start
    scene.frame_end = frame_end
    scene.frame_step = frame_step

    if frame_start == frame_end:
        scene.frame_set(frame_start)
        bpy.ops.render.render(write_still=True)
    else:
        bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()
