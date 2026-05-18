"""
Blender script for albedo (diffuse color, no lighting) rendering from GLB/GLTF files.
Runs INSIDE Blender's Python interpreter.
Invoked via: blender --background --python albedo.py -- <json_config>

Uses the Compositor DiffCol pass to output pure material base color without lighting.
"""
import json
import math
import sys


def import_glb(filepath):
    import bpy

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    bpy.ops.import_scene.gltf(filepath=filepath)
    print(f"Albedo: imported {filepath}")


def setup_albedo_compositor(output_dir, base_name):
    """Enable DiffCol pass and output albedo via compositor."""
    import bpy

    scene = bpy.context.scene
    scene.render.use_compositing = True
    bpy.context.view_layer.use_pass_diffuse_color = True

    # Blender 5.x: use compositing_node_group; Blender 4.x: use node_tree
    if hasattr(scene, 'compositing_node_group'):
        tree = scene.compositing_node_group
        if tree is None:
            tree = bpy.data.node_groups.new("Albedo_Compositor", 'CompositorNodeTree')
            scene.compositing_node_group = tree
    else:
        scene.use_nodes = True
        tree = scene.node_tree
    tree.nodes.clear()

    rl = tree.nodes.new("CompositorNodeRLayers")
    rl.location = (0, 0)

    # Combine DiffCol with original alpha
    alpha_node = tree.nodes.new("CompositorNodeSetAlpha")
    alpha_node.location = (300, 0)
    diffcol_output = rl.outputs.get("Diffuse Color") or rl.outputs.get("DiffCol")
    tree.links.new(diffcol_output, alpha_node.inputs["Image"])
    tree.links.new(rl.outputs["Alpha"], alpha_node.inputs["Alpha"])

    # Use Composite node — outputs to render.filepath set by render_multi_view
    composite = tree.nodes.new("CompositorNodeComposite")
    composite.location = (600, 0)
    tree.links.new(alpha_node.outputs["Image"], composite.inputs["Image"])

    print("Albedo: compositor set up for DiffCol pass")


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
        print("Albedo: Warning - no glb_file specified")
        return

    rv.normalize_model(bpy)

    scene = bpy.context.scene
    render = scene.render

    engine = config.get("engine", "BLENDER_EEVEE_NEXT")
    render.engine = rv.resolve_engine(engine)
    render.resolution_x = config.get("resolution_x", 1920)
    render.resolution_y = config.get("resolution_y", 1080)
    render.resolution_percentage = config.get("resolution_percentage", 100)

    fmt = config.get("output_format", "PNG")
    render.image_settings.file_format = fmt
    render.image_settings.color_mode = 'RGBA'
    render.film_transparent = True

    if render.engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        samples = config.get("samples")
        if samples is not None:
            scene.eevee.taa_render_samples = samples

    # HDR environment (for accurate GI influence on diffuse, though albedo ignores direct lighting)
    hdri_path = opts.get("hdri_path")
    env_texture = opts.get("env_texture")
    if hdri_path:
        rv.setup_hdri_world(hdri_path, env_texture)
    else:
        rv.setup_white_world(scene)

    mesh_objects = rv._get_model_mesh_objects(bpy)
    if not mesh_objects:
        print("Albedo: no mesh objects found")
        return

    center, bbox_size = rv.get_bounding_box_evaluated(bpy, mesh_objects)
    rv.setup_camera(scene, center, bbox_size, render.resolution_x, render.resolution_y)

    output_dir = config.get("output_dir", "./output")
    base_name = config.get("filename_pattern", "albedo")
    setup_albedo_compositor(output_dir, base_name)

    rv.render_multi_view(bpy, scene, rv.setup_camera, center, bbox_size, opts, config, "Albedo")


if __name__ == "__main__":
    main()
