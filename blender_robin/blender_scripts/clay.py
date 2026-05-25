"""
Blender script for white clay (white model) rendering from GLB/GLTF files.
Runs INSIDE Blender's Python interpreter.
Invoked via: blender --background --python clay.py -- <json_config>
"""
import json
import math
import sys


def setup_workbench_matcap(scene, matcap_name="basic_grey.exr", log=print):
    """Configure Workbench render engine with Solid MatCap shading."""
    import bpy

    shading = scene.display.shading
    shading.light = 'MATCAP'
    shading.color_type = 'MATERIAL'
    shading.background_type = 'THEME'  # transparent background in Workbench render

    try:
        shading.studio_light = matcap_name
    except Exception:
        log(f"Clay: matcap '{matcap_name}' not found, using default")

    log(f"Clay: Workbench matcap configured (light=MATCAP, color_type=MATERIAL, matcap={shading.studio_light})")


def create_simple_gray_material():
    """Workbench only reads mat.diffuse_color — no nodes needed."""
    import bpy

    mat = bpy.data.materials.new(name="Clay_Gray")
    mat.diffuse_color = (0.95, 0.95, 0.95, 1.0)  # Brighter white
    return mat


def apply_material_to_meshes(material, log=print):
    """Apply material to all mesh objects."""
    import bpy

    applied = 0
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        obj.data.materials.clear()
        obj.data.materials.append(material)
        applied += 1

    log(f"Clay: applied gray material to {applied} mesh(es)")
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

    rv.configure_log(config.get("enable_log", True))
    output_dir = config.get("output_dir", "./output")
    base_name = config.get("filename_pattern", "render")
    rv.open_log(output_dir, base_name, "clay")

    try:
        glb_file = opts.get("glb_file")
        if glb_file:
            rv.import_model(bpy, glb_file)
        else:
            rv.log("Clay: Warning - no glb_file specified")
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
        setup_workbench_matcap(scene, matcap_name, log=rv.log)

        mat = create_simple_gray_material()
        apply_material_to_meshes(mat, log=rv.log)

        mesh_objects = rv._get_model_mesh_objects(bpy)
        if not mesh_objects:
            rv.log("Clay: no mesh objects found")
            return

        center, bbox_size = rv.get_bounding_box_evaluated(bpy, mesh_objects)
        rv.setup_camera(scene, center, bbox_size, render.resolution_x, render.resolution_y)

        rv.render_multi_view(bpy, scene, rv.setup_camera, center, bbox_size, opts, config, "Clay")
    finally:
        rv.close_log()


if __name__ == "__main__":
    main()
