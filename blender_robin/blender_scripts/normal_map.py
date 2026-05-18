"""
Blender script for surface normal map rendering from GLB/GLTF files.
Runs INSIDE Blender's Python interpreter.
Invoked via: blender --background --python normal_map.py -- <json_config>

Uses Workbench engine with built-in check_normal+y.exr MatCap for normal visualization.
"""
import json
import math
import sys


def import_glb(filepath):
    import bpy

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    bpy.ops.import_scene.gltf(filepath=filepath)
    print(f"NormalMap: imported {filepath}")


def setup_workbench_normal(opts):
    """Configure Workbench engine with normal MatCap."""
    import bpy

    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'

    shading = scene.display.shading
    shading.light = 'MATCAP'
    shading.studio_light = 'check_normal+y.exr'
    shading.color_type = 'MATERIAL'

    scene.render.film_transparent = True

    # Optional wireframe overlay
    if opts.get("show_wireframe", False):
        shading.show_xray = False
        scene.display.shading.show_xray_wireframe = False
        # Workbench wireframe overlay via render settings
        scene.display.render_aa = 'OFF'

    print("NormalMap: Workbench engine configured with check_normal+y.exr MatCap")


def apply_flat_shading():
    """Apply flat shading to all mesh objects."""
    import bpy

    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH':
            for poly in obj.data.polygons:
                poly.use_smooth = False
            obj.data.update()

    print("NormalMap: applied flat shading")


def main() -> None:
    import bpy

    separator_idx = sys.argv.index("--")
    config_json = sys.argv[separator_idx + 1]
    config = json.loads(config_json)
    opts = config.get("script_options", {})

    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "render_views", os.path.join(os.path.dirname(__file__), "render_views.py"))
    rv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rv)

    glb_file = opts.get("glb_file")
    if glb_file:
        rv.import_model(bpy, glb_file)
    else:
        print("NormalMap: Warning - no glb_file specified")
        return

    rv.normalize_model(bpy)

    if opts.get("flat_shading", True):
        apply_flat_shading()

    scene = bpy.context.scene
    render = scene.render

    render.resolution_x = config.get("resolution_x", 1920)
    render.resolution_y = config.get("resolution_y", 1080)
    render.resolution_percentage = config.get("resolution_percentage", 100)

    fmt = config.get("output_format", "PNG")
    render.image_settings.file_format = fmt
    render.image_settings.color_mode = 'RGBA'

    setup_workbench_normal(opts)

    rv.setup_white_world(scene)

    mesh_objects = rv._get_model_mesh_objects(bpy)
    if not mesh_objects:
        print("NormalMap: no mesh objects found")
        return

    center, bbox_size = rv.get_bounding_box_evaluated(bpy, mesh_objects)
    rv.setup_camera(scene, center, bbox_size, render.resolution_x, render.resolution_y)

    rv.render_multi_view(bpy, scene, rv.setup_camera, center, bbox_size, opts, config, "NormalMap")


if __name__ == "__main__":
    main()
