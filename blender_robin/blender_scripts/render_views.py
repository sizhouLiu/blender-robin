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

def import_model(bpy, filepath):
    """Import a model file. Supports .glb, .gltf, and .blend files."""
    import os

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".blend":
        # Append all objects from the .blend file into the current scene
        with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
            data_to.objects = list(data_from.objects)
        for obj in data_to.objects:
            if obj is not None:
                bpy.context.collection.objects.link(obj)
        print(f"Import: loaded .blend file {filepath} ({len(data_to.objects)} objects)")
    else:
        bpy.ops.import_scene.gltf(filepath=filepath)
        print(f"Import: loaded {filepath}")


def _get_model_mesh_objects(bpy):
    """
    Get mesh objects that belong to the imported model hierarchy.
    Excludes orphan/helper meshes (like Icosphere) that are not part of the main model tree.
    Strategy: find the primary root (deepest hierarchy), collect all meshes under it.
    If all meshes are roots, return all of them.
    """
    all_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not all_meshes:
        return []

    # Separate meshes that have a parent chain vs orphan root meshes
    parented_meshes = [obj for obj in all_meshes if obj.parent is not None]

    if parented_meshes:
        # If there are parented meshes, those are the real model.
        # Orphan root meshes (like Icosphere) are likely helpers/artifacts.
        return parented_meshes

    # All meshes are roots - return all
    return all_meshes


def normalize_model(bpy, target_size=2.0):
    """
    Normalize imported model: center at origin and scale to target_size.
    Uses evaluated depsgraph to handle armature/shape-key deformations.
    """
    import mathutils

    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh_objects = _get_model_mesh_objects(bpy)
    if not mesh_objects:
        print("Normalize: no mesh objects found")
        return

    min_co = mathutils.Vector((float('inf'), float('inf'), float('inf')))
    max_co = mathutils.Vector((float('-inf'), float('-inf'), float('-inf')))

    for obj in mesh_objects:
        obj_eval = obj.evaluated_get(depsgraph)
        mesh_eval = obj_eval.to_mesh()
        if mesh_eval is None:
            continue
        mat = obj_eval.matrix_world
        for v in mesh_eval.vertices:
            world_co = mat @ v.co
            min_co.x = min(min_co.x, world_co.x)
            min_co.y = min(min_co.y, world_co.y)
            min_co.z = min(min_co.z, world_co.z)
            max_co.x = max(max_co.x, world_co.x)
            max_co.y = max(max_co.y, world_co.y)
            max_co.z = max(max_co.z, world_co.z)
        obj_eval.to_mesh_clear()

    center = (min_co + max_co) / 2
    bbox_size = max_co - min_co
    max_dim = max(bbox_size.x, bbox_size.y, bbox_size.z)

    if max_dim == 0:
        print("Normalize: model has zero size, skipping")
        return

    scale_factor = target_size / max_dim

    root_objects = [obj for obj in bpy.context.scene.objects if obj.parent is None]
    for obj in root_objects:
        obj.location = (obj.location - center) * scale_factor
        obj.scale *= scale_factor

    bpy.context.view_layer.update()

    # Force depsgraph re-evaluation for armature models
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()

    print(f"Normalize: centered and scaled by {scale_factor:.4f} (max_dim {max_dim:.4f} -> {target_size:.4f})")


def get_bounding_box_evaluated(bpy, mesh_objects):
    """
    Compute world-space bounding box using evaluated mesh data.
    Accounts for armature deformation, shape keys, and all modifiers.
    Returns (center, bbox_size).
    """
    import mathutils

    # Force depsgraph update to ensure transforms are current (critical after normalize_model)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    min_co = mathutils.Vector((float('inf'), float('inf'), float('inf')))
    max_co = mathutils.Vector((float('-inf'), float('-inf'), float('-inf')))

    for obj in mesh_objects:
        obj_eval = obj.evaluated_get(depsgraph)
        mesh_eval = obj_eval.to_mesh()
        if mesh_eval is None:
            continue
        mat = obj_eval.matrix_world
        for v in mesh_eval.vertices:
            world_co = mat @ v.co
            min_co.x = min(min_co.x, world_co.x)
            min_co.y = min(min_co.y, world_co.y)
            min_co.z = min(min_co.z, world_co.z)
            max_co.x = max(max_co.x, world_co.x)
            max_co.y = max(max_co.y, world_co.y)
            max_co.z = max(max_co.z, world_co.z)
        obj_eval.to_mesh_clear()

    center = (min_co + max_co) / 2
    bbox_size = max_co - min_co
    print(f"BBox: center=({center.x:.4f}, {center.y:.4f}, {center.z:.4f}), "
          f"size=({bbox_size.x:.4f}, {bbox_size.y:.4f}, {bbox_size.z:.4f})")
    return center, bbox_size


# ── Camera helpers ────────────────────────────────────────────────────────

def setup_camera(scene, center, bbox_size, resolution_x, resolution_y):
    """Standard camera setup: frames bbox from diagonal direction (1, -1, 0.6)."""
    import bpy
    import math
    import mathutils

    camera = scene.camera
    if not camera:
        cam_data = bpy.data.cameras.new("Camera")
        camera = bpy.data.objects.new("Camera", cam_data)
        scene.collection.objects.link(camera)
        scene.camera = camera

    cam_data = camera.data
    cam_data.clip_start = 0.01
    cam_data.clip_end = 100000

    aspect = resolution_x / resolution_y
    fov = cam_data.angle

    direction = mathutils.Vector((1.0, -1.0, 1.414)).normalized()

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

    import os as _os
    render = scene.render
    output_dir = config.get("output_dir", "./output")
    _os.makedirs(output_dir, exist_ok=True)
    base_name = config.get("filename_pattern", "render")

    all_views = ["diagonal", "front", "back", "left", "right", "top", "bottom", "diagonal_back"]
    requested_views = opts.get("views", ["diagonal"])
    closeup_count = opts.get("closeup_count", 0)
    do_composite = opts.get("composite", True)
    delete_views_after_composite = opts.get("delete_views_after_composite", False)
    delete_closeups_after_composite = opts.get("delete_closeups_after_composite", False)
    export_meta = opts.get("export_metadata", False)
    animation_frame = opts.get("animation_frame", 1)  # Default to frame 1

    # Set animation frame BEFORE computing bounding box and camera
    # This ensures the bounding box includes the animated pose (arms/legs extended, etc.)
    scene.frame_set(animation_frame)
    bpy.context.view_layer.update()

    # Recompute bounding box at the target animation frame
    mesh_objects = _get_model_mesh_objects(bpy)
    if mesh_objects:
        center, bbox_size = get_bounding_box_evaluated(bpy, mesh_objects)
        print(f"{label}: Recomputed bbox at frame {animation_frame}")

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
        bpy.ops.render.render(write_still=True)
        view_files.append(f"{base_name}{suffix}")
        print(f"{label}: {view_name} rendered to {filepath}")

    # --- Random closeups ---
    if closeup_count > 0:
        mesh_objects = _get_model_mesh_objects(bpy)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        bbox_diagonal = bbox_size.length
        closeup_ratio = 0.10
        sub_radius = bbox_diagonal * closeup_ratio / 2.0

        # Load camera positions only from explicit camera_json; otherwise always generate randomly
        chosen_points = []
        chosen_directions = []

        ref_camera_json = opts.get("camera_json", "")
        if ref_camera_json and _os.path.exists(ref_camera_json):
            try:
                with open(ref_camera_json, "r") as f:
                    cache_data = json.load(f)
                cached_points = cache_data.get("closeup_focus_points", [])
                cached_dirs = cache_data.get("closeup_directions", [])
                if len(cached_points) >= closeup_count and len(cached_dirs) >= closeup_count:
                    n = min(len(cached_points), len(cached_dirs), closeup_count)
                    chosen_points = [mathutils.Vector(p) for p in cached_points[:n]]
                    chosen_directions = [mathutils.Vector(d) for d in cached_dirs[:n]]
                    print(f"{label}: Loaded {n} closeup positions from {ref_camera_json}")
                else:
                    print(f"{label}: camera_json has {len(cached_points)} points but need {closeup_count}, ignoring")
            except Exception as e:
                print(f"{label}: Failed to load camera_json {ref_camera_json}: {e}")

        if len(chosen_points) != closeup_count:
            verts_world = []
            for obj in mesh_objects:
                obj_eval = obj.evaluated_get(depsgraph)
                mesh_eval = obj_eval.to_mesh()
                if mesh_eval is None:
                    continue
                mat = obj_eval.matrix_world
                for v in mesh_eval.vertices:
                    verts_world.append(mat @ v.co)
                obj_eval.to_mesh_clear()

            # Filter: only keep vertices within 80% of bbox from center
            inner_half = bbox_size * 0.4
            verts_inner = [
                v for v in verts_world
                if abs(v.x - center.x) <= inner_half.x
                and abs(v.y - center.y) <= inner_half.y
                and abs(v.z - center.z) <= inner_half.z
            ]
            if len(verts_inner) < 10:
                verts_inner = verts_world

            # Build a voxel density map to score candidate points.
            # Cells with more vertices represent dense geometry (seams, joints, details).
            import mathutils as _mu
            grid_res = 16
            gx = max(bbox_size.x, 1e-6)
            gy = max(bbox_size.y, 1e-6)
            gz = max(bbox_size.z, 1e-6)
            bmin = center - bbox_size * 0.5

            def _voxel_key(v):
                ix = int((v.x - bmin.x) / gx * grid_res)
                iy = int((v.y - bmin.y) / gy * grid_res)
                iz = int((v.z - bmin.z) / gz * grid_res)
                return (
                    min(max(ix, 0), grid_res - 1),
                    min(max(iy, 0), grid_res - 1),
                    min(max(iz, 0), grid_res - 1),
                )

            density = {}
            for v in verts_world:
                k = _voxel_key(v)
                density[k] = density.get(k, 0) + 1

            def _vert_score(v):
                return density.get(_voxel_key(v), 1)

            # Build weighted candidate pool from inner verts
            scores = [_vert_score(v) for v in verts_inner]
            total_score = sum(scores)

            def _weighted_choice(pool, pool_scores, pool_total, rng):
                r = rng.random() * pool_total
                acc = 0.0
                for v, s in zip(pool, pool_scores):
                    acc += s
                    if acc >= r:
                        return v
                return pool[-1]

            min_dist = bbox_diagonal * closeup_ratio * 0.8
            chosen_points = []
            max_attempts = 500
            rng = random.Random()

            # Closeup camera directions: cycle through different angles
            all_directions = [
                mathutils.Vector((1.0, -1.0, 1.414)).normalized(),   # diagonal front
                mathutils.Vector((-1.0, 1.0, 1.414)).normalized(),   # diagonal back
                mathutils.Vector((0.0, -1.0, 1.0)).normalized(),     # front elevated
                mathutils.Vector((0.0, 1.0, 1.0)).normalized(),      # back elevated
                mathutils.Vector((-1.0, 0.0, 1.0)).normalized(),     # left elevated
                mathutils.Vector((1.0, 0.0, 1.0)).normalized(),      # right elevated
            ]
            chosen_directions = []

            for ci in range(closeup_count):
                focus_point = center
                if verts_inner:
                    best_candidate = None
                    best_score = -1
                    for _ in range(max_attempts):
                        candidate = _weighted_choice(verts_inner, scores, total_score, rng)
                        if not chosen_points:
                            focus_point = candidate
                            best_candidate = None
                            break
                        dists = [(candidate - p).length for p in chosen_points]
                        if min(dists) >= min_dist:
                            s = _vert_score(candidate)
                            if s > best_score:
                                best_score = s
                                best_candidate = candidate
                            # Accept first high-density hit to avoid over-sampling
                            if s >= max(scores) * 0.6:
                                focus_point = candidate
                                best_candidate = None
                                break
                    if best_candidate is not None:
                        focus_point = best_candidate
                chosen_points.append(focus_point)
                chosen_directions.append(all_directions[ci % len(all_directions)])

            # Save camera positions to per-model cache
            try:
                cache_data = {
                    "closeup_focus_points": [[p.x, p.y, p.z] for p in chosen_points],
                    "closeup_directions": [[d.x, d.y, d.z] for d in chosen_directions],
                    "bbox_center": [center.x, center.y, center.z],
                    "bbox_size": [bbox_size.x, bbox_size.y, bbox_size.z],
                }
                run_id = opts.get("run_id", "")
                cache_suffix = f"_{run_id}" if run_id else ""
                camera_cache_path = f"{output_dir}/{base_name}{cache_suffix}_cameras.json"
                with open(camera_cache_path, "w") as f:
                    json.dump(cache_data, f, indent=2)
                print(f"{label}: Saved {len(chosen_points)} closeup positions to {camera_cache_path}")
            except Exception as e:
                print(f"{label}: Failed to save camera cache: {e}")

        cam_data.type = 'PERSP'
        for ci in range(closeup_count):
            closeup_suffix = f"_closeup{ci + 1}"
            focus_point = chosen_points[ci]
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

            # Use the cached/generated direction for this closeup
            direction = chosen_directions[ci]
            cam_pos = focus_point + direction * dist

            # Ensure camera is outside the model's bounding box to prevent blank renders
            half_bbox = bbox_size * 0.5
            bbox_min = center - half_bbox
            bbox_max = center + half_bbox

            # Check if camera is inside bounding box
            inside = (bbox_min.x < cam_pos.x < bbox_max.x and
                     bbox_min.y < cam_pos.y < bbox_max.y and
                     bbox_min.z < cam_pos.z < bbox_max.z)

            if inside:
                # Push camera outside the bounding box along the direction vector
                # Calculate how far we need to move to exit each face
                extra_dist = 0.0
                for axis in range(3):
                    if abs(direction[axis]) > 1e-6:
                        if direction[axis] > 0:
                            # Moving in positive direction, exit through max face
                            exit_dist = (bbox_max[axis] - cam_pos[axis]) / direction[axis]
                        else:
                            # Moving in negative direction, exit through min face
                            exit_dist = (bbox_min[axis] - cam_pos[axis]) / direction[axis]
                        if exit_dist > 0:
                            extra_dist = max(extra_dist, exit_dist)

                # Add safety margin (5% of max dimension)
                safety_margin = max_dim * 0.05
                cam_pos = cam_pos + direction * (extra_dist + safety_margin)
                dist = (cam_pos - focus_point).length
                print(f"{label}: closeup {ci + 1} camera was inside bbox, pushed out by {extra_dist + safety_margin:.3f}")

            camera.location = cam_pos
            look_dir = focus_point - camera.location
            rot_quat = look_dir.to_track_quat('-Z', 'Y')
            camera.rotation_euler = rot_quat.to_euler()
            cam_data.clip_start = max(0.0001, dist * 0.005)
            cam_data.clip_end = dist * 5

            filepath = f"{output_dir}/{base_name}{closeup_suffix}"
            render.filepath = filepath
            bpy.ops.render.render(write_still=True)
            closeup_files.append(f"{base_name}{closeup_suffix}")
            print(f"{label}: closeup {ci + 1} rendered to {filepath}")

    # --- Composite ---
    def _make_composite(bpy, files, out_path, w, h, cols, label_tag):
        if len(files) == 0:
            return
        rows = math.ceil(len(files) / cols)
        canvas = bpy.data.images.new(label_tag, width=w * cols, height=h * rows, alpha=True)
        canvas_pixels = [0.0] * (w * cols * h * rows * 4)
        for i, fname in enumerate(files):
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
        canvas.save_render(out_path)
        bpy.data.images.remove(canvas)
        print(f"{label}: composite saved to {out_path}")

    def _best_cols(n, img_w, img_h):
        """Return column count that makes the composite canvas closest to square."""
        if n <= 1:
            return 1
        img_aspect = img_w / img_h
        best_cols = 1
        best_diff = float("inf")
        for c in range(1, n + 1):
            r = math.ceil(n / c)
            canvas_aspect = (c * img_w) / (r * img_h)
            diff = abs(math.log(canvas_aspect / img_aspect) if img_aspect else canvas_aspect)
            diff = abs(math.log(canvas_aspect))
            if diff < best_diff:
                best_diff = diff
                best_cols = c
        return best_cols

    if do_composite:
        w = render.resolution_x
        h = render.resolution_y
        if len(view_files) > 1:
            cols_v = _best_cols(len(view_files), w, h)
            _make_composite(bpy, view_files, f"{output_dir}/{base_name}_all.png", w, h, cols_v, f"{label}_Views")
        if len(closeup_files) > 1:
            cols_c = _best_cols(len(closeup_files), w, h)
            _make_composite(bpy, closeup_files, f"{output_dir}/{base_name}_closeup_all.png", w, h, cols_c, f"{label}_Closeups")

        if delete_views_after_composite:
            import os
            ext = "." + render.image_settings.file_format.lower().replace("jpeg", "jpg")
            for fname in view_files:
                p = f"{output_dir}/{fname}{ext}"
                if os.path.exists(p):
                    os.remove(p)
                    print(f"{label}: deleted view {fname}{ext}")

        if delete_closeups_after_composite:
            import os
            ext = "." + render.image_settings.file_format.lower().replace("jpeg", "jpg")
            for fname in closeup_files:
                p = f"{output_dir}/{fname}{ext}"
                if os.path.exists(p):
                    os.remove(p)
                    print(f"{label}: deleted closeup {fname}{ext}")

    # --- Metadata ---
    if export_meta and meta_locations:
        env_tex = opts.get("env_texture", "")
        export_metadata(
            output_dir, camera_angle_x, default_lens, default_sensor_width,
            env_tex, meta_locations, base_name,
        )


# ── Shading helpers ───────────────────────────────────────────────────────


def shade_flat():
    """Set all mesh objects to flat shading."""
    import bpy

    for obj in bpy.data.objects:
        if obj.type == "MESH":
            for poly in obj.data.polygons:
                poly.use_smooth = False


def resolve_engine(name):
    """Resolve engine name to one available in this Blender version."""
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


def setup_white_world(scene, strength=1.0):
    """Set world background to pure white with given strength."""
    import bpy

    world = scene.world
    if not world:
        world = bpy.data.worlds.new("World")
        scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        bg.inputs["Strength"].default_value = strength
