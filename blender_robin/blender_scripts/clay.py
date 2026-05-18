"""
Blender script for white clay (white model) rendering from GLB/GLTF files.
Runs INSIDE Blender's Python interpreter.
Invoked via: blender --background --python clay.py -- <json_config>
"""
import json
import math
import sys


def import_glb(filepath):
    import bpy

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    bpy.ops.import_scene.gltf(filepath=filepath)
    print(f"Clay: imported {filepath}")


def setup_workbench_matcap(scene, matcap_name="basic_grey.exr"):
    """Configure Workbench render engine with Solid MatCap shading."""
    import bpy

    shading = scene.display.shading
    shading.light = 'MATCAP'
    shading.color_type = 'MATERIAL'
    shading.background_type = 'THEME'  # transparent background in Workbench render

    # Try to set the requested matcap
    try:
        shading.studio_light = matcap_name
    except Exception:
        print(f"Clay: matcap '{matcap_name}' not found, using default")

    print(f"Clay: Workbench matcap configured (light=MATCAP, color_type=MATERIAL, matcap={shading.studio_light})")


def create_simple_gray_material():
    """Workbench only reads mat.diffuse_color — no nodes needed."""
    import bpy

    mat = bpy.data.materials.new(name="Clay_Gray")
    mat.diffuse_color = (0.82, 0.82, 0.82, 1.0)
    return mat


def apply_material_to_meshes(material):
    """Apply material to all mesh objects."""
    import bpy

    applied = 0
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        obj.data.materials.clear()
        obj.data.materials.append(material)
        applied += 1

    print(f"Clay: applied gray material to {applied} mesh(es)")
    return applied


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
        print("Clay: Warning - no glb_file specified")
        return

    rv.normalize_model(bpy)

    scene = bpy.context.scene
    render = scene.render

    render.engine = 'BLENDER_WORKBENCH'
    render.resolution_x = config.get("resolution_x", 1920)
    render.resolution_y = config.get("resolution_y", 1080)
    render.resolution_percentage = config.get("resolution_percentage", 100)

    fmt = config.get("output_format", "PNG")
    render.image_settings.file_format = fmt
    render.image_settings.color_mode = 'RGBA'
    render.film_transparent = True

    matcap_name = opts.get("matcap", "basic_grey.exr")
    setup_workbench_matcap(scene, matcap_name)

    mat = create_simple_gray_material()
    apply_material_to_meshes(mat)

    mesh_objects = rv._get_model_mesh_objects(bpy)
    if not mesh_objects:
        print("Clay: no mesh objects found")
        return

    center, bbox_size = rv.get_bounding_box_evaluated(bpy, mesh_objects)
    rv.setup_camera(scene, center, bbox_size, render.resolution_x, render.resolution_y)

    rv.render_multi_view(bpy, scene, rv.setup_camera, center, bbox_size, opts, config, "Clay")


if __name__ == "__main__":
    main()
