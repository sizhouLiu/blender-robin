"""
Blender script for RGB full-body + random closeup rendering from GLB/GLTF files.
Runs INSIDE Blender's Python interpreter.
Invoked via: blender --background --python rgb_closeup.py -- <json_config>
"""
import json
import math
import random
import sys


def import_glb(filepath):
    import bpy

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    bpy.ops.import_scene.gltf(filepath=filepath)
    print(f"RGB Closeup: imported {filepath}")


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


def ensure_camera(scene):
    import bpy

    camera = scene.camera
    if not camera:
        cam_data = bpy.data.cameras.new("RGB_Camera")
        camera = bpy.data.objects.new("RGB_Camera", cam_data)
        scene.collection.objects.link(camera)
        scene.camera = camera
    camera.data.clip_start = 0.001
    camera.data.clip_end = 100000
    return camera


def frame_camera_on_bbox(camera, center, bbox_size, resolution_x, resolution_y):
    import mathutils

    cam_data = camera.data
    radius = bbox_size.length / 2.0
    aspect = resolution_x / resolution_y
    fov = cam_data.angle

    if aspect >= 1.0:
        vfov = 2.0 * math.atan(math.tan(fov / 2.0) / aspect)
    else:
        vfov = fov

    half_angle = min(fov / 2.0, vfov / 2.0)
    distance = radius / math.sin(half_angle) * 1.1

    direction = mathutils.Vector((1.0, -1.0, 0.6)).normalized()
    camera.location = center + direction * distance

    look_dir = center - camera.location
    rot_quat = look_dir.to_track_quat('-Z', 'Y')
    camera.rotation_euler = rot_quat.to_euler()

    cam_data.clip_end = max(cam_data.clip_end, distance * 3)
    return distance


def ensure_lighting(scene):
    import bpy
    import mathutils

    has_light = any(obj.type == "LIGHT" for obj in scene.objects)
    if has_light:
        return

    light_data = bpy.data.lights.new(name="RGB_Sun", type="SUN")
    light_data.energy = 3.0
    light_obj = bpy.data.objects.new("RGB_Sun", light_data)
    light_obj.rotation_euler = mathutils.Euler((0.8, 0.2, 0.5))
    scene.collection.objects.link(light_obj)

    fill_data = bpy.data.lights.new(name="RGB_Fill", type="SUN")
    fill_data.energy = 1.0
    fill_obj = bpy.data.objects.new("RGB_Fill", fill_data)
    fill_obj.rotation_euler = mathutils.Euler((-0.5, -0.8, -0.3))
    scene.collection.objects.link(fill_obj)


def setup_closeup_camera(camera, center, bbox_size, resolution_x, resolution_y):
    """Frame a specific part's bounding box, same logic as full-body but tighter."""
    import mathutils

    cam_data = camera.data
    radius = bbox_size.length / 2.0
    aspect = resolution_x / resolution_y
    fov = cam_data.angle

    if aspect >= 1.0:
        vfov = 2.0 * math.atan(math.tan(fov / 2.0) / aspect)
    else:
        vfov = fov

    half_angle = min(fov / 2.0, vfov / 2.0)
    distance = radius / math.sin(half_angle) * 1.15

    direction = mathutils.Vector((1.0, -1.0, 0.6)).normalized()
    camera.location = center + direction * distance

    look_dir = center - camera.location
    rot_quat = look_dir.to_track_quat('-Z', 'Y')
    camera.rotation_euler = rot_quat.to_euler()

    cam_data.clip_start = max(0.001, distance * 0.01)
    cam_data.clip_end = distance * 5

    print(f"RGB Closeup: part closeup, bbox size {bbox_size.length:.2f}, distance {distance:.2f}")


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
        print("RGB Closeup: Warning - no glb_file specified")
        return

    scene = bpy.context.scene
    render = scene.render

    engine = config.get("engine", "BLENDER_EEVEE_NEXT")
    render.engine = resolve_engine(engine)
    render.resolution_x = config.get("resolution_x", 1920)
    render.resolution_y = config.get("resolution_y", 1080)
    render.resolution_percentage = config.get("resolution_percentage", 100)

    fmt = config.get("output_format", "PNG")
    render.image_settings.file_format = fmt

    if render.engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        samples = config.get("samples")
        if samples is not None:
            scene.eevee.taa_render_samples = samples

    world = scene.world
    if not world:
        world = bpy.data.worlds.new("RGB_World")
        scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.8, 0.8, 0.8, 1.0)
        bg.inputs["Strength"].default_value = 1.0

    mesh_objects = [obj for obj in scene.objects if obj.type == "MESH"]
    if not mesh_objects:
        print("RGB Closeup: no mesh objects found")
        return

    center, bbox_size = get_bounding_box(mesh_objects)
    bbox_diagonal = bbox_size.length

    camera = ensure_camera(scene)
    ensure_lighting(scene)

    output_dir = config.get("output_dir", "./rgb_output")
    base_name = config.get("filename_pattern", "render")

    # --- Render 1: Full body ---
    frame_camera_on_bbox(camera, center, bbox_size, render.resolution_x, render.resolution_y)
    render.filepath = f"{output_dir}/{base_name}_full"
    scene.frame_set(1)
    bpy.ops.render.render(write_still=True)
    print(f"RGB Closeup: full body rendered to {render.filepath}")

    # --- Render 2: Random part closeup ---
    part = random.choice(mesh_objects)
    part_center, part_bbox = get_bounding_box([part])
    print(f"RGB Closeup: selected part '{part.name}' for closeup")
    setup_closeup_camera(camera, part_center, part_bbox, render.resolution_x, render.resolution_y)
    render.filepath = f"{output_dir}/{base_name}_closeup"
    bpy.ops.render.render(write_still=True)
    print(f"RGB Closeup: closeup rendered to {render.filepath}")


if __name__ == "__main__":
    main()
