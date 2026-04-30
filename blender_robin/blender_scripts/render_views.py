"""
Shared multi-view rendering logic for all Blender scripts.
Handles: views, closeups, composite.
"""
import math
import random


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

    camera = scene.camera
    if not camera:
        setup_camera_func(scene, center, bbox_size, render.resolution_x, render.resolution_y)
        camera = scene.camera
    cam_data = camera.data

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

    # Track view renders and closeup renders separately
    view_files = []
    closeup_files = []
    view_idx = 0

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

        filepath = f"{output_dir}/{base_name}{suffix}"
        render.filepath = filepath
        scene.frame_set(1)
        bpy.ops.render.render(write_still=True)
        view_files.append(f"{base_name}{suffix}")
        print(f"{label}: {view_name} rendered to {filepath}")

    # --- Random closeups (separate naming: base_name_closeup1, _closeup2, ...) ---
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

        # Pick spread-out focus points to avoid clustering
        min_dist = bbox_diagonal * closeup_ratio * 0.8
        chosen_points = []
        max_attempts = 100

        cam_data.type = 'PERSP'
        for ci in range(closeup_count):
            closeup_suffix = f"_closeup{ci + 1}"

            # Try to find a point far enough from previously chosen ones
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

    # --- Composite (views + closeups) ---
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
