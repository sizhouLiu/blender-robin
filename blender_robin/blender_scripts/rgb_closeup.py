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
    return distance


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

    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "render_views", os.path.join(os.path.dirname(__file__), "render_views.py"))
    rv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rv)
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

    hdri_path = opts.get("hdri_path")
    env_texture = opts.get("env_texture")
    if hdri_path:
        rv.setup_hdri_world(hdri_path, env_texture)
    else:
        rv.setup_white_world(scene)

    mesh_objects = rv._get_model_mesh_objects(bpy)
    if not mesh_objects:
        print("RGB Closeup: no mesh objects found")
        return

    center, bbox_size = rv.get_bounding_box_evaluated(bpy, mesh_objects)

    camera = ensure_camera(scene)

    def _setup_cam(sc, c, bs, rx, ry):
        cam = ensure_camera(sc)
        frame_camera_on_bbox(cam, c, bs, rx, ry)
        return cam

    rv.render_multi_view(bpy, scene, _setup_cam, center, bbox_size, opts, config, "RGB")


if __name__ == "__main__":
    main()
