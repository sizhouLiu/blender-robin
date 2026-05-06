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


def create_clay_material():
    import bpy

    mat = bpy.data.materials.new(name="Clay_White")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (300, 0)

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (0.85, 0.85, 0.85, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.6
    bsdf.location = (0, 0)

    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    return mat


def apply_material_to_meshes(material):
    import bpy

    applied = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        obj.data.materials.clear()
        obj.data.materials.append(material)
        applied += 1

    print(f"Clay: applied to {applied} mesh(es)")
    return applied


def get_bounding_box(mesh_objects):
    import mathutils

    min_co = mathutils.Vector((float('inf'), float('inf'), float('inf')))
    max_co = mathutils.Vector((float('-inf'), float('-inf'), float('-inf')))

    for obj in mesh_objects:
        for corner in obj.bound_box:
            world_corner = obj.matrix_world @ mathutils.Vector(corner)
            min_co.x = min(min_co.x, world_corner.x)
            min_co.y = min(min_co.y, world_corner.y)
            min_co.z = min(min_co.z, world_corner.z)
            max_co.x = max(max_co.x, world_corner.x)
            max_co.y = max(max_co.y, world_corner.y)
            max_co.z = max(max_co.z, world_corner.z)

    center = (min_co + max_co) / 2
    bbox_size = max_co - min_co
    return center, bbox_size


def setup_camera(scene, center, bbox_size, resolution_x, resolution_y):
    import bpy
    import mathutils

    camera = scene.camera
    if not camera:
        cam_data = bpy.data.cameras.new("Clay_Camera")
        camera = bpy.data.objects.new("Clay_Camera", cam_data)
        scene.collection.objects.link(camera)
        scene.camera = camera

    cam_data = camera.data
    cam_data.clip_start = 0.01
    cam_data.clip_end = 100000

    aspect = resolution_x / resolution_y
    fov = cam_data.angle  # horizontal FOV

    # Camera direction
    direction = mathutils.Vector((1.0, -1.0, 0.6)).normalized()

    # Project bbox onto camera's local axes to get tight framing
    # Camera right = direction x world_up, camera up = right x direction
    cam_forward = -direction
    world_up = mathutils.Vector((0, 0, 1))
    cam_right = cam_forward.cross(world_up).normalized()
    cam_up = cam_right.cross(cam_forward).normalized()

    # Half-extents of bbox
    hx, hy, hz = bbox_size.x / 2, bbox_size.y / 2, bbox_size.z / 2
    corners = [
        mathutils.Vector((sx * hx, sy * hy, sz * hz))
        for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)
    ]

    # Find max projected extent on camera right and up axes
    max_right = max(abs(c.dot(cam_right)) for c in corners)
    max_up = max(abs(c.dot(cam_up)) for c in corners)

    # Distance needed to fit horizontally and vertically
    dist_h = max_right / math.tan(fov / 2)
    vfov = 2 * math.atan(math.tan(fov / 2) / aspect)
    dist_v = max_up / math.tan(vfov / 2)

    distance = max(dist_h, dist_v) * 1.02  # 2% padding

    camera.location = center + direction * distance

    look_dir = center - camera.location
    rot_quat = look_dir.to_track_quat('-Z', 'Y')
    camera.rotation_euler = rot_quat.to_euler()

    cam_data.clip_end = max(cam_data.clip_end, distance * 3)


def ensure_lighting(scene):
    import bpy
    import mathutils

    has_light = any(obj.type == "LIGHT" for obj in scene.objects)
    if has_light:
        return

    # Key light
    key = bpy.data.lights.new(name="Clay_Key", type="SUN")
    key.energy = 3.0
    key_obj = bpy.data.objects.new("Clay_Key", key)
    key_obj.rotation_euler = mathutils.Euler((0.8, 0.2, 0.5))
    scene.collection.objects.link(key_obj)

    # Fill light
    fill = bpy.data.lights.new(name="Clay_Fill", type="SUN")
    fill.energy = 1.5
    fill_obj = bpy.data.objects.new("Clay_Fill", fill)
    fill_obj.rotation_euler = mathutils.Euler((-0.5, -0.8, -0.3))
    scene.collection.objects.link(fill_obj)


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
        print("Clay: Warning - no glb_file specified")
        return

    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "render_views", os.path.join(os.path.dirname(__file__), "render_views.py"))
    rv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rv)
    rv.normalize_model(bpy)

    material = create_clay_material()
    apply_material_to_meshes(material)

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

    # Light gray background for ambient lighting
    world = scene.world
    if not world:
        world = bpy.data.worlds.new("Clay_World")
        scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.2, 0.2, 0.2, 1.0)
        bg.inputs["Strength"].default_value = 1.0

    mesh_objects = [obj for obj in scene.objects if obj.type == "MESH"]
    if not mesh_objects:
        print("Clay: no mesh objects found")
        return

    center, bbox_size = get_bounding_box(mesh_objects)
    setup_camera(scene, center, bbox_size, render.resolution_x, render.resolution_y)
    ensure_lighting(scene)

    rv.render_multi_view(bpy, scene, setup_camera, center, bbox_size, opts, config, "Clay")


if __name__ == "__main__":
    main()
