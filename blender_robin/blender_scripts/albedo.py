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


def setup_camera(scene, center, bbox_size, resolution_x, resolution_y):
    import bpy
    import mathutils

    camera = scene.camera
    if not camera:
        cam_data = bpy.data.cameras.new("Albedo_Camera")
        camera = bpy.data.objects.new("Albedo_Camera", cam_data)
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


def setup_albedo_material_override():
    """
    Override all materials to output only the Base Color (albedo) without lighting.
    Works by replacing each material's node tree with a simple Emission node
    driven by the original Base Color, so the output is flat/unlit color.
    Preserves per-material Base Color textures.
    """
    import bpy

    modified = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None:
                continue
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links

            # Find existing Principled BSDF to extract Base Color
            principled = None
            for node in nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    principled = node
                    break

            # Get output node
            output = None
            for node in nodes:
                if node.type == 'OUTPUT_MATERIAL':
                    output = node
                    break
            if output is None:
                output = nodes.new("ShaderNodeOutputMaterial")
                output.location = (600, 0)

            # Create emission node for flat (unlit) color output
            emit = nodes.new("ShaderNodeEmission")
            emit.location = (400, 0)
            emit.inputs["Strength"].default_value = 1.0

            if principled is not None:
                # Connect Base Color from Principled to Emission Color
                base_color_socket = principled.inputs.get("Base Color")
                if base_color_socket and base_color_socket.links:
                    # There's a texture connected — rewire it to Emission
                    tex_link = base_color_socket.links[0]
                    tex_node = tex_link.from_node
                    tex_out = tex_link.from_socket
                    links.new(tex_out, emit.inputs["Color"])
                else:
                    # Plain color value
                    color = base_color_socket.default_value if base_color_socket else (0.8, 0.8, 0.8, 1.0)
                    emit.inputs["Color"].default_value = (color[0], color[1], color[2], 1.0)
            else:
                # No Principled BSDF — use default gray
                emit.inputs["Color"].default_value = (0.8, 0.8, 0.8, 1.0)

            # Wire Emission to output Surface
            links.new(emit.outputs["Emission"], output.inputs["Surface"])
            modified += 1

    print(f"Albedo: applied albedo material override to {modified} material slot(s)")


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
        print("Albedo: Warning - no glb_file specified")
        return

    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "render_views", os.path.join(os.path.dirname(__file__), "render_views.py"))
    rv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rv)
    rv.normalize_model(bpy)

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

    # HDR environment (for accurate GI influence on diffuse, though albedo ignores direct lighting)
    hdri_path = opts.get("hdri_path")
    env_texture = opts.get("env_texture")
    if hdri_path:
        rv.setup_hdri_world(hdri_path, env_texture)
    else:
        world = scene.world
        if not world:
            world = bpy.data.worlds.new("Albedo_World")
            scene.world = world
        world.use_nodes = True
        bg = world.node_tree.nodes.get("Background")
        if bg:
            bg.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            bg.inputs["Strength"].default_value = 1.0

    mesh_objects = rv._get_model_mesh_objects(bpy)
    if not mesh_objects:
        print("Albedo: no mesh objects found")
        return

    center, bbox_size = rv.get_bounding_box_evaluated(bpy, mesh_objects)
    setup_camera(scene, center, bbox_size, render.resolution_x, render.resolution_y)

    setup_albedo_material_override()

    output_dir = config.get("output_dir", "./output")
    base_name = config.get("filename_pattern", "albedo")

    rv.render_multi_view(bpy, scene, setup_camera, center, bbox_size, opts, config, "Albedo")


if __name__ == "__main__":
    main()
