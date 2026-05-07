"""
Shared multi-view rendering logic for all Blender scripts.
Handles: views, closeups, composite, HDR environment lighting, metadata export.
"""
import json
import math
import os
import random


# ── HDRI environment lighting ─────────────────────────────────────────────

ENV_TEXTURES_LIST = [
    "belfast_sunset_puresky_1k.exr",
    "brown_photostudio_02_1k.exr",
    "city.exr",
    "clarens_midday_1k.exr",
    "courtyard.exr",
    "evening_road_01_puresky_1k.exr",
    "industrial_sunset_puresky_1k.exr",
    "interior.exr",
    "kloofendal_overcast_puresky_1k.exr",
    "kloppenheim_06_puresky_1k.exr",
    "promenade_de_vidy_1k.exr",
    "resting_place_1k.exr",
    "studio_small_09_1k.exr",
    "sunset.exr",
]


def setup_hdri_world(hdri_path: str, env_texture: str = None):
    """Set up HDR environment map as world lighting."""
    import bpy

    scene = bpy.context.scene
    world = scene.world
    if not world:
        world = bpy.data.worlds.new("HDRI_World")
        scene.world = world

    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()

    env_node = nodes.new(type="ShaderNodeTexEnvironment")
    env_node.location = (0, 0)

    bg_node = nodes.new(type="ShaderNodeBackground")
    bg_node.location = (400, 0)

    output_node = nodes.new(type="ShaderNodeOutputWorld")
    output_node.location = (800, 0)

    links.new(env_node.outputs["Color"], bg_node.inputs["Color"])
    links.new(bg_node.outputs["Background"], output_node.inputs["Surface"])

    if env_texture is None:
        env_texture = "kloofendal_overcast_puresky_1k.exr"

    full_path = os.path.join(hdri_path, env_texture)
    if os.path.exists(full_path):
        bpy.ops.image.open(filepath=full_path)
        env_node.image = bpy.data.images.get(env_texture)
        print(f"HDRI: loaded {env_texture}")
    else:
        print(f"HDRI: {full_path} not found, using flat gray fallback")
        bg_node.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1.0)
        bg_node.inputs["Strength"].default_value = 1.0

    return env_texture


def hash_select_env_texture(model_id: str):
    """Deterministically pick an HDRI based on model ID hash."""
    idx = hash(model_id) % len(ENV_TEXTURES_LIST)
    return ENV_TEXTURES_LIST[idx]


# ── Model normalization ───────────────────────────────────────────────────

def normalize_model(bpy, target_size=2.0):
    """
    Normalize imported model: center at origin and scale to target_size.
    Handles parent-child hierarchies by operating on root objects only.
    """
    import mathutils

    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not mesh_objects:
        print("Normalize: no mesh objects found")
        return

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
    max_dim = max(bbox_size.x, bbox_size.y, bbox_size.z)

    if max_dim == 0:
        print("Normalize: model has zero size, skipping")
        return

    scale_factor = target_size / max_dim

    all_objects = list(bpy.context.scene.objects)
    root_objects = [obj for obj in all_objects if obj.parent is None]

    for obj in root_objects:
        obj.location -= center
        obj.scale *= scale_factor

    bpy.context.view_layer.update()

    print(f"Normalize: centered and scaled by {scale_factor:.4f} (max_dim {max_dim:.4f} -> {target_size:.4f})")


# ── Camera helpers ────────────────────────────────────────────────────────

def get_camera_positions_on_sphere(center, radius, elevation_deg=10):
    """Return 4 camera positions at fixed azimuths (45/135/225/315°) on a sphere."""
    import mathutils

    phi = math.radians(90 - elevation_deg)
    positions = []

    for angle in [45, 135, 225, 315]:
        theta = math.radians(angle)
        r = radius
        x = center[0] + r * math.sin(phi) * math.cos(theta)
        y = center[1] + r * math.sin(phi) * math.sin(theta)
        z = center[2] + r * math.cos(phi)
        positions.append((mathutils.Vector((x, y, z)), theta, phi))

    return positions


def build_transform_matrix(translation, rotation_euler):
    """Build a 4x4 transformation matrix from translation and Euler rotation."""
    import mathutils

    translation = mathutils.Vector(translation)
    mat = mathutils.Matrix.Translation(translation)
    rot_mat = rotation_euler.to_matrix().to_4x4()
    return mat @ rot_mat


def listify_matrix(matrix):
    """Convert a mathutils.Matrix to a list-of-lists for JSON."""
    result = []
    for row in matrix:
        result.append(list(row))
    return result


# ── Metadata export ───────────────────────────────────────────────────────

def export_metadata(output_dir, camera_angle_x, camera_lens, sensor_width, env_texture,
                    view_locations, base_name="frame"):
    """Write meta.json with camera parameters for NeRF / 3DGS training."""
    out_data = {
        "camera_angle_x": camera_angle_x,
        "camera_lens": camera_lens,
        "sensor_width": sensor_width,
        "env_texture": env_texture,
        "frames": [],
    }

    for idx, loc_info in enumerate(view_locations):
        frame = {
            "file_path": f"./{base_name}_{idx:04d}.png",
            "transform_matrix": listify_matrix(loc_info["matrix"]),
            "camera_type": loc_info.get("type", "PERSP"),
        }
        out_data["frames"].append(frame)

    meta_path = os.path.join(output_dir, "meta.json")
    with open(meta_path, "w") as f:
        json.dump(out_data, f, indent=2)
    print(f"Metadata: exported to {meta_path}")


# ── Multi-view rendering ─────────────────────────────────────────────────

def render_multi_view(bpy, scene, setup_camera_func, center, bbox_size, opts, config, label):
    """Render multiple views + closeups + composite for any render mode."""
    import mathutils

    render = scene.render
    output_dir = config.get("output_dir", "./output")
    base_name = config.get("filename_pattern", "render")

    all_views = ["diagonal", "front", "back", "left", "right", "top", "bottom", "diagonal_back"]
    requested_views = opts.get("views", ["diagonal"])
    closeup_count = opts.get("closeup_count", 0)
    do_composite = opts.get("composite", True)
    export_meta = opts.get("export_metadata", False)

    camera = scene.camera
    if not camera:
        setup_camera_func(scene, center, bbox_size, render.resolution_x, render.resolution_y)
        camera = scene.camera
    cam_data = camera.data

    default_sensor_width = cam_data.sensor_width
    default_lens = cam_data.lens
    camera_angle_x = 2.0 * math.atan(default_sensor_width / 2.0 / default_lens)

    ortho_views = {
        "front":  (mathutils.Vector((0, -1, 0)),  mathutils.Euler((math.pi / 2, 0, 0))),
        "back":   (mathutils.Vector((0, 1, 0)),   mathutils.Euler((math.pi / 2, 0, math.pi))),
        "left":   (mathutils.Vector((-1, 0, 0)),  mathutils.Euler((math.pi / 2, 0, -math.pi / 2))),
        "right":  (mathutils.Vector((1, 0, 0)),   mathutils.Euler((math.pi / 2, 0, math.pi / 2))),
        "top":    (mathutils.Vector((0, 0, 1)),   mathutils.Euler((0, 0, 0))),
        "bottom": (mathutils.Vector((0, 0, -1)),  mathutils.Euler((math.pi, 0, 0))),
    }

    max_dim = max(bbox_size.x, bbox_size.y, bbox_size.z)
    distance = max_dim * 2

    view_files = []
    closeup_files = []
    view_idx = 0
    meta_locations = []

    # --- Multi-view renders ---
    for view_name in requested_views:
        view_idx += 1
        suffix = "" if view_idx == 1 else str(view_idx)

        if view_name == "diagonal":
            cam_data.type = 'PERSP'
            setup_camera_func(scene, center, bbox_size, render.resolution_x, render.resolution_y)
        elif view_name == "diagonal_back":
            cam_data.type = 'PERSP'
            setup_camera_func(scene, center, bbox_size, render.resolution_x, render.resolution_y)
            direction2 = mathutils.Vector((-1.0, 1.0, 0.6)).normalized()
            camera.location = center + direction2 * (camera.location - center).length
            look_dir = center - camera.location
            rot_quat = look_dir.to_track_quat('-Z', 'Y')
            camera.rotation_euler = rot_quat.to_euler()
        elif view_name == "fixed_4view":
            cam_data.type = 'PERSP'
            sphere_radius = max_dim * 1.5
            positions = get_camera_positions_on_sphere(center, sphere_radius, elevation_deg=10)
            fixed_view_idx = 0
            for pos, theta, phi in positions:
                fixed_view_idx += 1
                fv_suffix = f"_4v{fixed_view_idx}"
                camera.location = pos
                look_dir = center - camera.location
                rot_quat = look_dir.to_track_quat('-Z', 'Y')
                camera.rotation_euler = rot_quat.to_euler()
                cam_data.lens = default_lens
                cam_data.clip_start = 0.01
                cam_data.clip_end = sphere_radius * 5

                if export_meta:
                    rot_mat = rot_quat.to_matrix().to_4x4()
                    meta_locations.append({
                        "matrix": build_transform_matrix(pos, camera.rotation_euler),
                        "type": "PERSP",
                    })

                filepath = f"{output_dir}/{base_name}{fv_suffix}"
                render.filepath = filepath
                bpy.ops.render.render(write_still=True)
                view_files.append(f"{base_name}{fv_suffix}")
                print(f"{label}: fixed_4view #{fixed_view_idx} rendered to {filepath}")

            # Skip other per-view logic — fixed_4view handles its own sub-views
            continue
        elif view_name in ortho_views:
            cam_data.type = 'ORTHO'
            cam_data.ortho_scale = max_dim * 1.05
            direction, rotation = ortho_views[view_name]
            camera.location = center + direction * distance
            camera.rotation_euler = rotation
            cam_data.clip_start = 0.01
            cam_data.clip_end = distance * 3
        else:
            continue

        if export_meta:
            meta_locations.append({
                "matrix": build_transform_matrix(camera.location, camera.rotation_euler),
                "type": cam_data.type,
            })

        filepath = f"{output_dir}/{base_name}{suffix}"
        render.filepath = filepath
        scene.frame_set(1)
        bpy.ops.render.render(write_still=True)
        view_files.append(f"{base_name}{suffix}")
        print(f"{label}: {view_name} rendered to {filepath}")

    # --- Random closeups ---
    if closeup_count > 0:
        mesh_objects = [obj for obj in scene.objects if obj.type == "MESH"]
        bbox_diagonal = bbox_size.length
        closeup_ratio = 0.10
        sub_radius = bbox_diagonal * closeup_ratio / 2.0

        verts_world = []
        for obj in mesh_objects:
            mat = obj.matrix_world
            for v in obj.data.vertices:
                verts_world.append(mat @ v.co)

        min_dist = bbox_diagonal * closeup_ratio * 0.8
        chosen_points = []
        max_attempts = 100

        cam_data.type = 'PERSP'
        for ci in range(closeup_count):
            closeup_suffix = f"_closeup{ci + 1}"

            focus_point = center
            if verts_world:
                for _ in range(max_attempts):
                    candidate = random.choice(verts_world)
                    if not chosen_points:
                        focus_point = candidate
                        break
                    dists = [((candidate - p).length) for p in chosen_points]
                    if min(dists) >= min_dist:
                        focus_point = candidate
                        break
                else:
                    focus_point = random.choice(verts_world)
            chosen_points.append(focus_point)
            sub_bbox_size = mathutils.Vector((sub_radius * 2, sub_radius * 2, sub_radius * 2))

            radius = sub_bbox_size.length / 2.0
            aspect = render.resolution_x / render.resolution_y
            fov = cam_data.angle
            if aspect >= 1.0:
                vfov = 2.0 * math.atan(math.tan(fov / 2.0) / aspect)
            else:
                vfov = fov
            half_angle = min(fov / 2.0, vfov / 2.0)
            dist = radius / math.sin(half_angle) * 1.15

            direction = mathutils.Vector((1.0, -1.0, 0.6)).normalized()
            camera.location = focus_point + direction * dist
            look_dir = focus_point - camera.location
            rot_quat = look_dir.to_track_quat('-Z', 'Y')
            camera.rotation_euler = rot_quat.to_euler()
            cam_data.clip_start = max(0.001, dist * 0.01)
            cam_data.clip_end = dist * 5

            filepath = f"{output_dir}/{base_name}{closeup_suffix}"
            render.filepath = filepath
            bpy.ops.render.render(write_still=True)
            closeup_files.append(f"{base_name}{closeup_suffix}")
            print(f"{label}: closeup {ci + 1} rendered to {filepath}")

    # --- Composite ---
    all_files = view_files + closeup_files
    if do_composite and len(all_files) > 1:
        w = render.resolution_x
        h = render.resolution_y
        cols = 4
        rows = math.ceil(len(all_files) / cols)
        canvas = bpy.data.images.new(f"{label}_All", width=w * cols, height=h * rows, alpha=True)
        canvas_pixels = [0.0] * (w * cols * h * rows * 4)

        for i, fname in enumerate(all_files):
            col = i % cols
            row = rows - 1 - i // cols
            path = f"{output_dir}/{fname}.png"
            img = bpy.data.images.load(path)
            src = list(img.pixels)
            for y in range(h):
                src_start = y * w * 4
                dst_x = col * w
                dst_y = row * h + y
                dst_start = (dst_y * w * cols + dst_x) * 4
                canvas_pixels[dst_start:dst_start + w * 4] = src[src_start:src_start + w * 4]
            bpy.data.images.remove(img)

        canvas.pixels = canvas_pixels
        canvas.file_format = 'PNG'
        all_path = f"{output_dir}/{base_name}_all.png"
        canvas.save_render(all_path)
        bpy.data.images.remove(canvas)
        print(f"{label}: composite rendered to {all_path}")

    # --- Metadata ---
    if export_meta and meta_locations:
        env_tex = opts.get("env_texture", "")
        export_metadata(
            output_dir, camera_angle_x, default_lens, default_sensor_width,
            env_tex, meta_locations, base_name,
        )


# ── Shading helpers ───────────────────────────────────────────────────────

def clear_normal_map():
    """Disconnect normal map inputs from all Principled BSDF nodes."""
    import bpy

    for material in bpy.data.materials:
        if not material.use_nodes:
            continue
        node_tree = material.node_tree
        try:
            bsdf = node_tree.nodes["Principled BSDF"]
            if bsdf.inputs["Normal"].is_linked:
                for link in bsdf.inputs["Normal"].links:
                    node_tree.links.remove(link)
        except Exception:
            pass


def shade_flat():
    """Set all mesh objects to flat shading."""
    import bpy

    for obj in bpy.data.objects:
        if obj.type == "MESH":
            for poly in obj.data.polygons:
                poly.use_smooth = False
