"""
Blender script for surface normal map rendering from GLB/GLTF files.
Runs INSIDE Blender's Python interpreter.
Invoked via: blender --background --python normal_map.py -- <json_config>

Uses Blender's built-in Normal render pass — no material override needed.
Outputs normals as RGB color: X→R, Y→G, Z→B, remapped from [-1,1] to [0,1].
Flat surface facing camera ≈ (0.5, 0.5, 1.0) = classic light-blue normal map.
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


def setup_normal_compositor(output_dir, base_name):
    """Enable Normal pass and output via compositor with remapping."""
    import bpy

    scene = bpy.context.scene
    scene.render.use_compositing = True
    scene.use_nodes = True
    bpy.context.view_layer.use_pass_normal = True

    tree = scene.node_tree
    tree.nodes.clear()

    rl = tree.nodes.new("CompositorNodeRLayers")
    rl.location = (0, 0)

    # Remap normal from [-1,1] → [0,1]: multiply by 0.5 then add 0.5
    multiply = tree.nodes.new("CompositorNodeMixRGB")
    multiply.blend_type = 'MULTIPLY'
    multiply.inputs[0].default_value = 1.0  # Factor
    multiply.inputs[2].default_value = (0.5, 0.5, 0.5, 1.0)
    multiply.location = (300, 0)

    add = tree.nodes.new("CompositorNodeMixRGB")
    add.blend_type = 'ADD'
    add.inputs[0].default_value = 1.0
    add.inputs[2].default_value = (0.5, 0.5, 0.5, 0.0)
    add.location = (500, 0)

    tree.links.new(rl.outputs["Normal"], multiply.inputs[1])
    tree.links.new(multiply.outputs["Image"], add.inputs[1])

    # Combine with original alpha
    alpha_node = tree.nodes.new("CompositorNodeSetAlpha")
    alpha_node.location = (700, 0)
    tree.links.new(add.outputs["Image"], alpha_node.inputs["Image"])
    tree.links.new(rl.outputs["Alpha"], alpha_node.inputs["Alpha"])

    file_output = tree.nodes.new("CompositorNodeOutputFile")
    file_output.base_path = output_dir
    file_output.location = (900, 0)
    file_output.format.file_format = scene.render.image_settings.file_format
    file_output.format.color_mode = "RGBA"
    file_output.file_slots[0].path = base_name + "_normal"
    file_output.file_slots[0].use_node_format = True
    tree.links.new(alpha_node.outputs["Image"], file_output.inputs["Image"])

    print("NormalMap: compositor set up for Normal pass")


def setup_camera(scene, center, bbox_size, resolution_x, resolution_y):
    import bpy
    import mathutils

    camera = scene.camera
    if not camera:
        cam_data = bpy.data.cameras.new("Normal_Camera")
        camera = bpy.data.objects.new("Normal_Camera", cam_data)
        scene.collection.objects.link(camera)
        scene.camera = camera

    cam_data = camera.data
    cam_data.clip_start = 0.01
    cam_data.clip_end = 100000

    aspect = resolution_x / resolution_y
    fov = cam_data.angle

    direction = mathutils.Vector((1.0, -1.0, 0.6)).normalized()

    cam_forward = -direction
    world_up = mathutils.Vector((0, 0, 1))
    cam_right = cam_forward.cross(world_up).normalized()
    cam_up = cam_right.cross(cam_forward).normalized()

    hx, hy, hz = bbox_size.x / 2, bbox_size.y / 2, bbox_size.z / 2
    corners = [
        mathutils.Vector((sx * hx, sy * hy, sz * hz))
        for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)
    ]

    max_right = max(abs(c.dot(cam_right)) for c in corners)
    max_up = max(abs(c.dot(cam_up)) for c in corners)

    dist_h = max_right / math.tan(fov / 2)
    vfov = 2 * math.atan(math.tan(fov / 2) / aspect)
    dist_v = max_up / math.tan(vfov / 2)

    distance = max(dist_h, dist_v) * 1.02

    camera.location = center + direction * distance

    look_dir = center - camera.location
    rot_quat = look_dir.to_track_quat('-Z', 'Y')
    camera.rotation_euler = rot_quat.to_euler()

    cam_data.clip_end = max(cam_data.clip_end, distance * 3)
    return camera


def resolve_engine(name):
    import bpy

    available = set()
    for engine in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items:
        available.add(engine.identifier)

    if name in available:
        return name

    aliases = {
        "BLENDER_EEVEE_NEXT": "BLENDER_EEVEE",
        "BLENDER_EEVEE": "BLENDER_EEVEE_NEXT",
    }
    alt = aliases.get(name)
    if alt and alt in available:
        return alt

    return "BLENDER_EEVEE" if "BLENDER_EEVEE" in available else list(available)[0]


def main() -> None:
    import bpy

    separator_idx = sys.argv.index("--")
    config_json = sys.argv[separator_idx + 1]
    config = json.loads(config_json)
    opts = config.get("script_options", {})

    glb_file = opts.get("glb_file")
    if glb_file:
        import_glb(glb_file)
    else:
        print("NormalMap: Warning - no glb_file specified")
        return

    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "render_views", os.path.join(os.path.dirname(__file__), "render_views.py"))
    rv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rv)
    rv.normalize_model(bpy)

    # Apply flat shading if requested (cleaner normal visualization)
    if opts.get("flat_shading"):
        rv.shade_flat()

    scene = bpy.context.scene
    render = scene.render

    engine = config.get("engine", "BLENDER_EEVEE_NEXT")
    render.engine = resolve_engine(engine)
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

    # HDR environment or simple dark background
    hdri_path = opts.get("hdri_path")
    env_texture = opts.get("env_texture")
    if hdri_path:
        rv.setup_hdri_world(hdri_path, env_texture)
    else:
        world = scene.world
        if not world:
            world = bpy.data.worlds.new("Normal_World")
            scene.world = world
        world.use_nodes = True
        bg = world.node_tree.nodes.get("Background")
        if bg:
            bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
            bg.inputs["Strength"].default_value = 0.0

    mesh_objects = [obj for obj in scene.objects if obj.type == "MESH"]
    if not mesh_objects:
        print("NormalMap: no mesh objects found")
        return

    center, bbox_size = rv.get_bounding_box_evaluated(bpy, mesh_objects)
    setup_camera(scene, center, bbox_size, render.resolution_x, render.resolution_y)

    output_dir = config.get("output_dir", "./output")
    base_name = config.get("filename_pattern", "normal")
    setup_normal_compositor(output_dir, base_name)

    rv.render_multi_view(bpy, scene, setup_camera, center, bbox_size, opts, config, "NormalMap")


if __name__ == "__main__":
    main()
