"""
Blender script for UV checker rendering from GLB/GLTF files.
Runs INSIDE Blender's Python interpreter.
Invoked via: blender --background --python uv_checker_glb.py -- <json_config>
"""
import json
import sys


def load_color_grid_image(log=print):
    """Load color_grid.png from script directory. Fail fast if missing."""
    import bpy, os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    png_path = os.path.join(script_dir, "color_grid.png")
    if not os.path.exists(png_path):
        raise FileNotFoundError(
            f"UV Checker: color_grid.png not found at {png_path}. "
            "Run generate_color_grid.py first."
        )
    img = bpy.data.images.load(png_path, check_existing=True)
    img.colorspace_settings.name = 'sRGB'
    log(f"UV Checker: loaded color grid from {png_path} ({img.size[0]}x{img.size[1]})")
    return img


def _normalize_uv_edges(uv_edges):
    """
    Shift UV islands that lie outside [0,1] back into [0,1] space.
    Each island (connected component of edges) is shifted by the integer floor
    of its own bounding-box minimum, so the island shape is never distorted.
    uv_edges: list of (u1x, u1y, u2x, u2y) tuples.
    Returns a new list with the same structure but shifted coordinates.
    """
    import math
    import numpy as np

    if not uv_edges:
        return uv_edges

    arr = np.array(uv_edges, dtype=np.float64)

    # Build adjacency: each edge connects two UV points (rounded to avoid float noise).
    # Use union-find to group edges into islands, then shift each island as a unit.
    ROUND = 6  # decimal places for UV coord key

    def _key(u, v):
        return (round(float(u), ROUND), round(float(v), ROUND))

    # Union-Find on edge indices
    parent = list(range(len(arr)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[b] = a

    # Map UV point key -> first edge index that introduced it
    point_to_edge = {}
    for i, (u1, v1, u2, v2) in enumerate(arr):
        for k in (_key(u1, v1), _key(u2, v2)):
            if k in point_to_edge:
                union(i, point_to_edge[k])
            else:
                point_to_edge[k] = i

    # Group edges by island root
    from collections import defaultdict
    islands = defaultdict(list)
    for i in range(len(arr)):
        islands[find(i)].append(i)

    # Shift each island by floor of its bounding-box min
    result = arr.copy()
    for indices in islands.values():
        idx = np.array(indices)
        island = arr[idx]  # shape (N, 4)
        all_u = np.concatenate([island[:, 0], island[:, 2]])
        all_v = np.concatenate([island[:, 1], island[:, 3]])
        shift_u = math.floor(np.min(all_u))
        shift_v = math.floor(np.min(all_v))
        if shift_u != 0 or shift_v != 0:
            result[idx, 0] -= shift_u
            result[idx, 1] -= shift_v
            result[idx, 2] -= shift_u
            result[idx, 3] -= shift_v

    return result.tolist()


def _bake_uv_image(obj, output_path, size, seams_only, color=(1.0, 1.0, 1.0, 1.0), log=print):
    """
    Draw UV edges for obj onto a transparent canvas and save as PNG.
    seams_only=True: only edges where adjacent faces have different UV coords (seams).
    seams_only=False: all UV edges (island outlines + interior).
    color: RGBA tuple for line color (default white).
    Returns True on success.
    """
    import bpy, os, bmesh
    import numpy as np

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    width, height = size
    canvas = np.zeros((height, width, 4), dtype=np.float32)

    bm = bmesh.new()
    bm.from_mesh(obj.data)

    if not bm.loops.layers.uv.active:
        bm.free()
        log(f"UV Checker: WARNING - '{obj.name}' has no active UV layer")
        return False

    uv_layer = bm.loops.layers.uv.active
    UV_EPS = 1e-5  # tolerance for UV coordinate comparison

    uv_edges = []

    if seams_only:
        # A UV seam is an edge shared by 2+ faces where the UV coords differ on the two sides.
        # For each edge, collect the UV coords from all adjacent loops.
        # If the two sides disagree → seam.
        for edge in bm.edges:
            if len(edge.link_faces) < 2:
                # Boundary edge — always a seam in UV space
                for face in edge.link_faces:
                    for loop in face.loops:
                        if loop.edge == edge:
                            uv1 = loop[uv_layer].uv.copy()
                            uv2 = loop.link_loop_next[uv_layer].uv.copy()
                            uv_edges.append((uv1.x, uv1.y, uv2.x, uv2.y))
                            break
            else:
                # Collect the UV pair for this edge from each adjacent face
                side_uvs = []
                for face in edge.link_faces:
                    for loop in face.loops:
                        if loop.edge == edge:
                            uv1 = loop[uv_layer].uv.copy()
                            uv2 = loop.link_loop_next[uv_layer].uv.copy()
                            side_uvs.append((uv1, uv2))
                            break
                # Compare first side against all others
                if len(side_uvs) >= 2:
                    u1a, u1b = side_uvs[0]
                    is_seam = False
                    for u2a, u2b in side_uvs[1:]:
                        # The other side connects the same verts but in reverse order
                        if ((abs(u1a.x - u2b.x) > UV_EPS or abs(u1a.y - u2b.y) > UV_EPS) or
                                (abs(u1b.x - u2a.x) > UV_EPS or abs(u1b.y - u2a.y) > UV_EPS)):
                            is_seam = True
                            break
                    if is_seam:
                        uv_edges.append((u1a.x, u1a.y, u1b.x, u1b.y))
    else:
        # All UV edges: just walk every face's loops
        for face in bm.faces:
            loops = face.loops
            n = len(loops)
            for i, loop in enumerate(loops):
                uv1 = loop[uv_layer].uv
                uv2 = loops[(i + 1) % n][uv_layer].uv
                uv_edges.append((uv1.x, uv1.y, uv2.x, uv2.y))

    bm.free()

    if uv_edges:
        uv_edges = _normalize_uv_edges(uv_edges)
        uv_edges = np.array(uv_edges, dtype=np.float32)
        uv_edges[:, [0, 2]] = np.clip(uv_edges[:, [0, 2]] * width,  0, width  - 1)
        uv_edges[:, [1, 3]] = np.clip((1.0 - uv_edges[:, [1, 3]]) * height, 0, height - 1)
        _draw_lines_batch(canvas, uv_edges, width, height, color, thickness=3)

    img = bpy.data.images.new("UV_Bake_Temp", width=width, height=height, alpha=True)
    img.pixels.foreach_set(canvas.ravel())
    _save_render_standard(img, output_path)
    bpy.data.images.remove(img)
    return True


def export_uv_layout_for_mesh(obj, output_path, size=(1024, 1024), log=print):
    """Export full UV layout (all edges) for UV layout composite image."""
    import bpy, os, bmesh
    import numpy as np

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Try bpy.ops.uv.export_layout first (works in GUI mode)
    try:
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        result = bpy.ops.uv.export_layout(
            filepath=output_path,
            export_all=True,
            mode='PNG',
            size=size,
            opacity=0.0,
            check_existing=False,
        )

        if 'FINISHED' in result:
            log(f"UV Checker: exported UV layout for '{obj.name}' to {output_path}")
            return True
    except (RuntimeError, SystemError):
        log(f"UV Checker: bpy.ops.uv.export_layout unavailable (background mode), using bmesh fallback")

    success = _bake_uv_image(obj, output_path, size, seams_only=False, log=log)
    if success:
        log(f"UV Checker: exported UV layout for '{obj.name}' to {output_path} (bmesh fallback)")
    else:
        log(f"UV Checker: WARNING - UV layout export failed for '{obj.name}'")
    return success


def bake_seam_overlay_for_mesh(obj, output_path, size=(1024, 1024), log=print):
    """Bake UV seam lines only (UV-discontinuous edges) for use as red overlay in material."""
    success = _bake_uv_image(obj, output_path, size, seams_only=True, log=log)
    if success:
        log(f"UV Checker: baked seam overlay for '{obj.name}' to {output_path}")
    else:
        log(f"UV Checker: WARNING - seam overlay bake failed for '{obj.name}'")
    return success


def bake_seam_overlay_to_image(obj, size=(1024, 1024), log=print):
    """Bake UV seam lines to a Blender image (in-memory, no disk I/O). Returns bpy.data.images or None."""
    import bpy, bmesh
    import numpy as np

    width, height = size
    canvas = np.zeros((height, width, 4), dtype=np.float32)
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    if not bm.loops.layers.uv.active:
        bm.free()
        log(f"UV Checker: WARNING - '{obj.name}' has no active UV layer")
        return None

    uv_layer = bm.loops.layers.uv.active
    UV_EPS = 1e-5
    uv_edges = []

    for edge in bm.edges:
        if len(edge.link_faces) < 2:
            for face in edge.link_faces:
                for loop in face.loops:
                    if loop.edge == edge:
                        uv1 = loop[uv_layer].uv.copy()
                        uv2 = loop.link_loop_next[uv_layer].uv.copy()
                        uv_edges.append((uv1.x, uv1.y, uv2.x, uv2.y))
                        break
        else:
            side_uvs = []
            for face in edge.link_faces:
                for loop in face.loops:
                    if loop.edge == edge:
                        uv1 = loop[uv_layer].uv.copy()
                        uv2 = loop.link_loop_next[uv_layer].uv.copy()
                        side_uvs.append((uv1, uv2))
                        break
            if len(side_uvs) >= 2:
                u1a, u1b = side_uvs[0]
                is_seam = False
                for u2a, u2b in side_uvs[1:]:
                    if ((abs(u1a.x - u2b.x) > UV_EPS or abs(u1a.y - u2b.y) > UV_EPS) or
                            (abs(u1b.x - u2a.x) > UV_EPS or abs(u1b.y - u2a.y) > UV_EPS)):
                        is_seam = True
                        break
                if is_seam:
                    uv_edges.append((u1a.x, u1a.y, u1b.x, u1b.y))
    bm.free()

    if uv_edges:
        uv_edges = _normalize_uv_edges(uv_edges)
        uv_edges = np.array(uv_edges, dtype=np.float32)
        uv_edges[:, [0, 2]] = np.clip(uv_edges[:, [0, 2]] * width, 0, width - 1)
        uv_edges[:, [1, 3]] = np.clip(uv_edges[:, [1, 3]] * height, 0, height - 1)  # 不翻转 V（内存版直接用）
        _draw_lines_batch(canvas, uv_edges, width, height, color=(1.0, 1.0, 1.0, 1.0), thickness=3)

    img = bpy.data.images.new(f"UV_Seam_{obj.name}", width=width, height=height, alpha=True)
    img.pixels.foreach_set(canvas.ravel())
    img.update()
    img.pack()
    img.colorspace_settings.name = 'Non-Color'
    log(f"UV Checker: baked seam overlay for '{obj.name}' (in-memory)")
    return img


def _save_render_standard(img, output_path):
    """Save image using Standard view transform to avoid AgX/Filmic color shift."""
    import bpy
    scene = bpy.context.scene
    cm = scene.view_settings
    prev_view = cm.view_transform
    prev_look = cm.look
    prev_exposure = cm.exposure
    prev_gamma = cm.gamma
    try:
        cm.view_transform = 'Standard'
        cm.look = 'None'
        cm.exposure = 0.0
        cm.gamma = 1.0
        img.save_render(output_path)
    finally:
        cm.view_transform = prev_view
        cm.look = prev_look
        cm.exposure = prev_exposure
        cm.gamma = prev_gamma


def _draw_lines_batch(canvas, edges, width, height, color=(1.0, 1.0, 1.0, 1.0), thickness=3):
    """Batch draw lines on canvas. edges: Nx4 array of (x0, y0, x1, y1)."""
    import numpy as np

    if len(edges) == 0:
        return

    for x0, y0, x1, y1 in edges.astype(int):
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        x, y = x0, y0
        points = []
        while True:
            points.append((y, x))
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy
        if not points:
            continue
        pts = np.array(points)
        if thickness > 1:
            offsets = np.arange(thickness) - thickness // 2
            if dx >= dy:
                ys = (pts[:, 0:1] + offsets).ravel()
                xs = np.repeat(pts[:, 1], thickness)
            else:
                ys = np.repeat(pts[:, 0], thickness)
                xs = (pts[:, 1:2] + offsets).ravel()
            mask = (ys >= 0) & (ys < height) & (xs >= 0) & (xs < width)
            canvas[ys[mask], xs[mask]] = color
        else:
            mask = (pts[:, 0] >= 0) & (pts[:, 0] < height) & (pts[:, 1] >= 0) & (pts[:, 1] < width)
            canvas[pts[mask, 0], pts[mask, 1]] = color


def _draw_line_numpy(canvas, x0, y0, x1, y1, width, height, color=(1.0, 1.0, 1.0, 1.0), thickness=3):
    """Draw a line on canvas using Bresenham algorithm with configurable thickness."""
    import numpy as np

    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy

    x, y = x0, y0
    points = []

    while True:
        points.append((y, x))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy

    if not points:
        return

    pts = np.array(points)  # shape (N, 2): col0=y, col1=x

    if thickness > 1:
        offsets = np.arange(thickness) - thickness // 2
        # Expand perpendicular to the dominant direction
        if dx >= dy:  # mostly horizontal → expand vertically
            ys = (pts[:, 0:1] + offsets).ravel()
            xs = np.repeat(pts[:, 1], thickness)
        else:          # mostly vertical → expand horizontally
            ys = np.repeat(pts[:, 0], thickness)
            xs = (pts[:, 1:2] + offsets).ravel()
        mask = (ys >= 0) & (ys < height) & (xs >= 0) & (xs < width)
        canvas[ys[mask], xs[mask]] = color
    else:
        mask = (pts[:, 0] >= 0) & (pts[:, 0] < height) & (pts[:, 1] >= 0) & (pts[:, 1] < width)
        canvas[pts[mask, 0], pts[mask, 1]] = color


def _draw_lines_batch_vectorized(canvas, edges, width, height, color=(1.0, 1.0, 1.0, 1.0), thickness=3):
    """Vectorized batch drawing of all lines. Much faster than loop over _draw_line_numpy.

    edges: numpy array of shape (N, 4) containing [x0, y0, x1, y1] per line.
    """
    import numpy as np

    if len(edges) == 0:
        return

    # For each line, sample points along it using linspace
    # Use a fixed number of samples per line proportional to its length
    x0, y0, x1, y1 = edges[:, 0], edges[:, 1], edges[:, 2], edges[:, 3]
    lengths = np.maximum(np.abs(x1 - x0), np.abs(y1 - y0)).astype(int) + 1

    # To avoid huge memory, cap samples per line
    max_samples = min(int(np.max(lengths)) + 1, 200)

    all_xs = []
    all_ys = []

    for i in range(len(edges)):
        n = min(lengths[i], max_samples)
        if n < 2:
            n = 2
        ts = np.linspace(0, 1, n)
        xs = (x0[i] + ts * (x1[i] - x0[i])).astype(int)
        ys = (y0[i] + ts * (y1[i] - y0[i])).astype(int)
        all_xs.append(xs)
        all_ys.append(ys)

    xs = np.concatenate(all_xs)
    ys = np.concatenate(all_ys)

    # Apply thickness
    if thickness > 1:
        offsets = np.arange(thickness) - thickness // 2
        xs_thick = (xs[:, None] + offsets).ravel()
        ys_thick = np.repeat(ys, thickness)
        mask = (ys_thick >= 0) & (ys_thick < height) & (xs_thick >= 0) & (xs_thick < width)
        canvas[ys_thick[mask], xs_thick[mask]] = color
    else:
        mask = (ys >= 0) & (ys < height) & (xs >= 0) & (xs < width)
        canvas[ys[mask], xs[mask]] = color


def create_per_mesh_material(obj, uv_layout_img, grid_img=None, checker_scale=None):
    """Create material with color grid or checker base + optional red seam overlay.

    Args:
        obj: Blender mesh object
        uv_layout_img: Seam overlay image (or None)
        grid_img: Color grid image (for color_grid style, or None)
        checker_scale: Checker scale (for checker style, or None)
    """
    import bpy

    mat_name = f"UV_Checker_{obj.name}"
    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Output
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (500, 0)

    # Principled BSDF
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (200, 0)
    bsdf.inputs["Roughness"].default_value = 1.0
    spec_input = bsdf.inputs.get("Specular IOR Level") or bsdf.inputs.get("Specular")
    if spec_input:
        spec_input.default_value = 0.0
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    # UV coordinate source
    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-600, 0)

    # Base texture: either color grid or checker
    if checker_scale is not None:
        # Checker mode
        base_tex = nodes.new("ShaderNodeTexChecker")
        base_tex.inputs["Scale"].default_value = checker_scale
        base_tex.location = (-350, 100)
        links.new(tex_coord.outputs["UV"], base_tex.inputs["Vector"])
        base_output = base_tex.outputs["Color"]
    else:
        # Color grid mode
        base_tex = nodes.new("ShaderNodeTexImage")
        base_tex.image = grid_img
        base_tex.location = (-350, 100)
        links.new(tex_coord.outputs["UV"], base_tex.inputs["Vector"])
        base_output = base_tex.outputs["Color"]

    # If no UV layout image, connect base directly to BSDF
    if uv_layout_img is None:
        links.new(base_output, bsdf.inputs["Base Color"])
        return mat

    # UV layout texture (seam overlay)
    seam_tex = nodes.new("ShaderNodeTexImage")
    seam_tex.image = uv_layout_img
    seam_tex.location = (-350, -150)
    seam_tex.image.colorspace_settings.name = 'Non-Color'
    links.new(tex_coord.outputs["UV"], seam_tex.inputs["Vector"])

    # MixRGB: blend base with red using seam alpha as factor
    mix = nodes.new("ShaderNodeMixRGB")
    mix.blend_type = 'MIX'
    mix.location = (-50, 0)
    mix.inputs["Color2"].default_value = (1.0, 0.1, 0.1, 1.0)  # bright red
    links.new(seam_tex.outputs["Alpha"], mix.inputs["Fac"])
    links.new(base_output, mix.inputs["Color1"])
    links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])

    return mat


def _bake_uv_image_group(entries, output_path, size, seams_only, color=(1.0, 1.0, 1.0, 1.0), thickness=1, log=print):
    """Draw UV edges for a group of (obj, face_index_set_or_None) entries onto a single canvas.

    face_index_set: set of face indices to include, or None to include all faces.
    For seams_only, an edge is included only if at least one adjacent face is in the set.

    UV coordinates are NOT normalized - if UVs extend beyond [0,1], the canvas will fit the actual UV bounds.
    """
    import bpy, os, bmesh
    import numpy as np

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    width, height = size
    UV_EPS = 1e-5

    all_uv_edges = []

    for obj, face_filter in entries:
        bm = bmesh.new()
        bm.from_mesh(obj.data)

        if not bm.loops.layers.uv.active:
            bm.free()
            log(f"UV Checker: WARNING - '{obj.name}' has no active UV layer")
            continue

        uv_layer = bm.loops.layers.uv.active
        uv_edges = []

        if seams_only:
            for edge in bm.edges:
                # Only process edges adjacent to at least one face in the filter
                relevant_faces = [f for f in edge.link_faces
                                  if face_filter is None or f.index in face_filter]
                if not relevant_faces:
                    continue

                if len(edge.link_faces) < 2:
                    for face in relevant_faces:
                        for loop in face.loops:
                            if loop.edge == edge:
                                uv1 = loop[uv_layer].uv.copy()
                                uv2 = loop.link_loop_next[uv_layer].uv.copy()
                                uv_edges.append((uv1.x, uv1.y, uv2.x, uv2.y))
                                break
                else:
                    side_uvs = []
                    for face in edge.link_faces:
                        for loop in face.loops:
                            if loop.edge == edge:
                                uv1 = loop[uv_layer].uv.copy()
                                uv2 = loop.link_loop_next[uv_layer].uv.copy()
                                side_uvs.append((uv1, uv2))
                                break
                    if len(side_uvs) >= 2:
                        u1a, u1b = side_uvs[0]
                        is_seam = False
                        for u2a, u2b in side_uvs[1:]:
                            if ((abs(u1a.x - u2b.x) > UV_EPS or abs(u1a.y - u2b.y) > UV_EPS) or
                                    (abs(u1b.x - u2a.x) > UV_EPS or abs(u1b.y - u2a.y) > UV_EPS)):
                                is_seam = True
                                break
                        if is_seam:
                            uv_edges.append((u1a.x, u1a.y, u1b.x, u1b.y))
        else:
            for face in bm.faces:
                if face_filter is not None and face.index not in face_filter:
                    continue
                loops = face.loops
                n = len(loops)
                for i, loop in enumerate(loops):
                    uv1 = loop[uv_layer].uv
                    uv2 = loops[(i + 1) % n][uv_layer].uv
                    uv_edges.append((uv1.x, uv1.y, uv2.x, uv2.y))

        bm.free()
        all_uv_edges.extend(uv_edges)

    if not all_uv_edges:
        # No UV data, create empty image
        canvas = np.zeros((height, width, 4), dtype=np.float32)
        img = bpy.data.images.new("UV_Bake_Temp", width=width, height=height, alpha=True)
        img.pixels.foreach_set(canvas.ravel())
        _save_render_standard(img, output_path)
        bpy.data.images.remove(img)
        return True

    # Compute actual UV bounding box (no normalization)
    arr = np.array(all_uv_edges, dtype=np.float32)
    all_u = np.concatenate([arr[:, 0], arr[:, 2]])
    all_v = np.concatenate([arr[:, 1], arr[:, 3]])
    u_min, u_max = np.min(all_u), np.max(all_u)
    v_min, v_max = np.min(all_v), np.max(all_v)

    # Add 5% padding
    u_range = u_max - u_min
    v_range = v_max - v_min
    if u_range < 1e-6:
        u_range = 1.0
    if v_range < 1e-6:
        v_range = 1.0

    u_min -= u_range * 0.05
    u_max += u_range * 0.05
    v_min -= v_range * 0.05
    v_max += v_range * 0.05

    # Map UV coords to canvas pixels
    # save_render() flips V automatically (Blender bottom-up → PNG top-down)
    # so we do NOT flip V here; U is left-to-right, matching Blender UV editor
    canvas = np.zeros((height, width, 4), dtype=np.float32)
    arr[:, 0] = (arr[:, 0] - u_min) / (u_max - u_min) * (width - 1)
    arr[:, 2] = (arr[:, 2] - u_min) / (u_max - u_min) * (width - 1)
    arr[:, 1] = (arr[:, 1] - v_min) / (v_max - v_min) * (height - 1)
    arr[:, 3] = (arr[:, 3] - v_min) / (v_max - v_min) * (height - 1)

    arr = np.clip(arr, 0, [width-1, height-1, width-1, height-1])

    _draw_lines_batch(canvas, arr, width, height, color, thickness)

    img = bpy.data.images.new("UV_Bake_Temp", width=width, height=height, alpha=True)
    img.pixels.foreach_set(canvas.ravel())
    _save_render_standard(img, output_path)
    bpy.data.images.remove(img)

    log(f"UV Checker: UV range for this group: U=[{u_min:.3f}, {u_max:.3f}], V=[{v_min:.3f}, {v_max:.3f}]")
    return True


def _material_has_basecolor_texture(mat):
    """Check if material has a texture connected to Base Color (Principled BSDF) or Color (Emission)."""
    if not mat or not mat.use_nodes:
        return False

    for node in mat.node_tree.nodes:
        # Check Principled BSDF Base Color input
        if node.type == 'BSDF_PRINCIPLED':
            base_color_input = node.inputs.get('Base Color')
            if base_color_input and base_color_input.links:
                return True

        # Check Emission Color input (for KHR_materials_unlit)
        if node.type == 'EMISSION':
            color_input = node.inputs.get('Color')
            if color_input and color_input.links:
                return True

    return False


def _group_objects_by_material(mesh_objects, require_basecolor=False, log=print):
    """Group mesh faces by material. Returns list of (mat_name, [(obj, face_index_set)]).

    A single mesh with multiple material slots is split into per-material face groups.
    If require_basecolor=True, materials without a Base Color texture are skipped.
    """
    from collections import defaultdict
    groups = {}   # mat_name -> {obj -> set of face indices}
    order = []
    skipped = []

    def _should_include(mat):
        if not require_basecolor:
            return True
        return _material_has_basecolor_texture(mat)

    for obj in mesh_objects:
        mats = obj.data.materials
        if not mats:
            if not require_basecolor:
                key = "__no_material__"
                if key not in groups:
                    groups[key] = {}
                    order.append(key)
                groups[key].setdefault(obj, None)
            else:
                skipped.append(f"{obj.name}(no material)")
            continue

        # Single material slot: no need to filter by face index
        if len(mats) == 1:
            mat = mats[0]
            if not _should_include(mat):
                skipped.append(f"{obj.name}({mat.name if mat else 'None'})")
                continue
            key = mat.name if mat else "__no_material__"
            if key not in groups:
                groups[key] = {}
                order.append(key)
            groups[key].setdefault(obj, None)
            continue

        # Multiple material slots: split faces by material_index, skip faces with no basecolor
        face_sets = defaultdict(set)
        for poly in obj.data.polygons:
            mat = mats[poly.material_index] if poly.material_index < len(mats) else None
            if not _should_include(mat):
                skipped.append(f"{obj.name}:{poly.material_index}({mat.name if mat else 'None'})")
                continue
            key = mat.name if mat else "__no_material__"
            face_sets[key].add(poly.index)

        for key, face_set in face_sets.items():
            if key not in groups:
                groups[key] = {}
                order.append(key)
            if obj in groups[key] and groups[key][obj] is None:
                pass
            elif obj in groups[key]:
                groups[key][obj] |= face_set
            else:
                groups[key][obj] = face_set

    if skipped:
        unique_skipped = list(dict.fromkeys(skipped))
        log(f"UV Checker: skipped {len(unique_skipped)} material(s) without Base Color texture: {', '.join(unique_skipped[:5])}{'...' if len(unique_skipped) > 5 else ''}")

    # Convert to list of (mat_name, [(obj, face_filter), ...])
    result = []
    for key in order:
        entries = [(obj, fs) for obj, fs in groups[key].items()]
        result.append((key, entries))
    return result


def _bake_uv_canvas_group(entries, size, seams_only, color, thickness, log=print):
    """Same as _bake_uv_image_group but returns numpy canvas directly (no disk I/O)."""
    import bmesh
    import numpy as np

    width, height = size
    UV_EPS = 1e-5
    all_uv_edges = []

    for obj, face_filter in entries:
        bm = bmesh.new()
        bm.from_mesh(obj.data)

        if not bm.loops.layers.uv.active:
            bm.free()
            log(f"UV Checker: WARNING - '{obj.name}' has no active UV layer")
            continue

        uv_layer = bm.loops.layers.uv.active
        uv_edges = []

        if seams_only:
            for edge in bm.edges:
                relevant_faces = [f for f in edge.link_faces
                                  if face_filter is None or f.index in face_filter]
                if not relevant_faces:
                    continue
                if len(edge.link_faces) < 2:
                    for face in relevant_faces:
                        for loop in face.loops:
                            if loop.edge == edge:
                                uv1 = loop[uv_layer].uv.copy()
                                uv2 = loop.link_loop_next[uv_layer].uv.copy()
                                uv_edges.append((uv1.x, uv1.y, uv2.x, uv2.y))
                                break
                else:
                    side_uvs = []
                    for face in edge.link_faces:
                        for loop in face.loops:
                            if loop.edge == edge:
                                uv1 = loop[uv_layer].uv.copy()
                                uv2 = loop.link_loop_next[uv_layer].uv.copy()
                                side_uvs.append((uv1, uv2))
                                break
                    if len(side_uvs) >= 2:
                        u1a, u1b = side_uvs[0]
                        is_seam = False
                        for u2a, u2b in side_uvs[1:]:
                            if ((abs(u1a.x - u2b.x) > UV_EPS or abs(u1a.y - u2b.y) > UV_EPS) or
                                    (abs(u1b.x - u2a.x) > UV_EPS or abs(u1b.y - u2a.y) > UV_EPS)):
                                is_seam = True
                                break
                        if is_seam:
                            uv_edges.append((u1a.x, u1a.y, u1b.x, u1b.y))
        else:
            for face in bm.faces:
                if face_filter is not None and face.index not in face_filter:
                    continue
                loops = face.loops
                n = len(loops)
                for i, loop in enumerate(loops):
                    uv1 = loop[uv_layer].uv
                    uv2 = loops[(i + 1) % n][uv_layer].uv
                    uv_edges.append((uv1.x, uv1.y, uv2.x, uv2.y))

        bm.free()
        all_uv_edges.extend(uv_edges)

    canvas = np.zeros((height, width, 4), dtype=np.float32)
    if not all_uv_edges:
        return canvas

    arr = np.array(all_uv_edges, dtype=np.float32)
    all_u = np.concatenate([arr[:, 0], arr[:, 2]])
    all_v = np.concatenate([arr[:, 1], arr[:, 3]])
    u_min, u_max = np.min(all_u), np.max(all_u)
    v_min, v_max = np.min(all_v), np.max(all_v)

    u_range = u_max - u_min if u_max - u_min > 1e-6 else 1.0
    v_range = v_max - v_min if v_max - v_min > 1e-6 else 1.0
    u_min -= u_range * 0.05; u_max += u_range * 0.05
    v_min -= v_range * 0.05; v_max += v_range * 0.05

    arr[:, 0] = (arr[:, 0] - u_min) / (u_max - u_min) * (width - 1)
    arr[:, 2] = (arr[:, 2] - u_min) / (u_max - u_min) * (width - 1)
    arr[:, 1] = (arr[:, 1] - v_min) / (v_max - v_min) * (height - 1)
    arr[:, 3] = (arr[:, 3] - v_min) / (v_max - v_min) * (height - 1)
    arr = np.clip(arr, 0, [width - 1, height - 1, width - 1, height - 1])

    _draw_lines_batch(canvas, arr, width, height, color, thickness)
    return canvas


def export_uv_layout_composite_grouped(groups, output_path, cell_size=512, log=print):
    """Export UV layout from pre-computed material groups into a grid PNG using numpy.
    Objects sharing the same material are drawn together in one cell.
    Draws all UV edges in white, then overlays seams in red."""
    import bpy, os, math
    import numpy as np

    if not groups:
        return

    n = len(groups)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    canvas_w = cols * cell_size
    canvas_h = rows * cell_size

    canvas = np.zeros((canvas_h, canvas_w, 4), dtype=np.float32)

    for i, (mat_name, entries) in enumerate(groups):
        col = i % cols
        row = i // cols

        src_all = _bake_uv_canvas_group(entries, (cell_size, cell_size), seams_only=False,
                                         color=(1.0, 1.0, 1.0, 1.0), thickness=1, log=log)
        src_seam = _bake_uv_canvas_group(entries, (cell_size, cell_size), seams_only=True,
                                          color=(1.0, 0.1, 0.1, 1.0), thickness=3, log=log)

        alpha_seam = src_seam[:, :, 3:4]
        composite = src_all * (1 - alpha_seam) + src_seam * alpha_seam

        y0 = row * cell_size
        x0 = col * cell_size
        canvas[y0:y0 + cell_size, x0:x0 + cell_size] = composite

    out_img = bpy.data.images.new(
        "UV_Layout_Composite", width=canvas_w, height=canvas_h, alpha=True
    )
    out_img.pixels.foreach_set(canvas.ravel())
    _save_render_standard(out_img, output_path)
    bpy.data.images.remove(out_img)

    group_summary = ", ".join(
        f"{name}({sum(1 for _ in entries)} part(s))" for name, entries in groups
    )
    log(f"UV Checker: UV layout composite saved to {output_path} ({cols}x{rows} grid, {n} material group(s): {group_summary})")




def export_blender_uv_layout_composite_grouped(groups, output_path, uv_layout_images, cell_size=2048, log=print):
    """Export Blender built-in UV layout per material group, composite into same grid as the numpy version.
    Requires foreground mode (bpy.ops.uv.export_layout needs a window context).
    Overlays seam lines in red using pre-baked uv_layout_images."""
    import bpy, os, math, tempfile, shutil
    import bmesh
    import numpy as np

    if not groups:
        return

    n = len(groups)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    canvas_w = cols * cell_size
    canvas_h = rows * cell_size

    canvas = np.zeros((canvas_h, canvas_w, 4), dtype=np.float32)

    tmp_dir = tempfile.mkdtemp(prefix="uv_blender_layout_")

    def _export_group_layout(entries, out_path):
        """Select only this group's faces, export, restore."""
        hidden_info = []
        bpy.ops.object.select_all(action='DESELECT')

        for obj, face_filter in entries:
            if not obj.data.uv_layers:
                continue
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

            if face_filter is not None:
                bm = bmesh.new()
                bm.from_mesh(obj.data)
                bm.faces.ensure_lookup_table()
                states = [f.hide for f in bm.faces]
                for f in bm.faces:
                    f.hide = f.index not in face_filter
                bm.to_mesh(obj.data)
                obj.data.update()
                hidden_info.append((obj, bm, states))

        try:
            bpy.ops.uv.export_layout(
                filepath=out_path,
                export_all=True,
                mode='PNG',
                size=(cell_size, cell_size),
                opacity=0.25,
            )
        finally:
            for obj, bm, states in hidden_info:
                for f, state in zip(bm.faces, states):
                    f.hide = state
                bm.to_mesh(obj.data)
                obj.data.update()
                bm.free()
            bpy.ops.object.select_all(action='DESELECT')

    try:
        for i, (mat_name, entries) in enumerate(groups):
            col = i % cols
            row = i // cols

            tmp_path = os.path.join(tmp_dir, f"uv_blender_{i:04d}.png")
            _export_group_layout(entries, tmp_path)

            uv_img = bpy.data.images.load(tmp_path, check_existing=False)
            uv_img.colorspace_settings.name = 'Non-Color'
            cell = np.array(uv_img.pixels, dtype=np.float32).reshape((cell_size, cell_size, 4)).copy()
            bpy.data.images.remove(uv_img)

            # Overlay seam lines in red
            for obj, _ in entries:
                seam_img = uv_layout_images.get(obj.name)
                if seam_img is None:
                    continue
                sw, sh = seam_img.size
                if sw != cell_size or sh != cell_size:
                    seam_img.scale(cell_size, cell_size)
                seam = np.array(seam_img.pixels, dtype=np.float32).reshape((cell_size, cell_size, 4))
                mask = seam[..., 0] > 0.1
                cell[mask] = (1.0, 0.0, 0.0, 1.0)

            y0 = row * cell_size
            x0 = col * cell_size
            canvas[y0:y0 + cell_size, x0:x0 + cell_size] = cell

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    out_img = bpy.data.images.new(
        "UV_Blender_Layout_Composite", width=canvas_w, height=canvas_h, alpha=True
    )
    out_img.pixels.foreach_set(canvas.ravel())
    _save_render_standard(out_img, output_path)
    bpy.data.images.remove(out_img)

    group_summary = ", ".join(
        f"{name}({sum(1 for _ in entries)} part(s))" for name, entries in groups
    )
    log(f"UV Checker: Blender UV layout composite saved to {output_path} ({cols}x{rows} grid, {n} group(s): {group_summary})")


def main() -> None:
    import bpy, os

    separator_idx = sys.argv.index("--")
    config_json = sys.argv[separator_idx + 1]
    config = json.loads(config_json)
    opts = config.get("script_options", {})

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "render_views", os.path.join(os.path.dirname(__file__), "render_views.py"))
    rv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rv)

    output_dir = config.get("output_dir", "./output")
    base_name = config.get("filename_pattern", "render")
    rv.configure_log(config.get("enable_log", True))
    rv.open_log(output_dir, base_name, "uv_checker")

    try:
        rv.timer_start("total")

        rv.timer_start("import_model")
        glb_file = opts.get("glb_file")
        if glb_file:
            rv.import_model(bpy, glb_file)
        else:
            rv.log("UV Checker: Warning - no glb_file specified in script_options")
        rv.timer_end("import_model")

        rv.normalize_model(bpy)

        style = opts.get("style", "color_grid")
        scale = opts.get("scale", 8.0)
        enable_seam_overlay = opts.get("enable_seam_overlay", True)
        export_uv_layout = opts.get("export_uv_layout", True)
        export_blender_uv = opts.get("export_blender_uv", False)
        rv.log(f"UV Checker: style={style}, enable_seam_overlay={enable_seam_overlay}, export_uv_layout={export_uv_layout}, export_blender_uv={export_blender_uv}")

        mesh_objects = rv._get_model_mesh_objects(bpy)
        uv_mesh_objects = [obj for obj in mesh_objects if obj.data.uv_layers]

        grid_img = None
        original_material_groups = []
        uv_layout_images = {}

        if not uv_mesh_objects:
            rv.log("UV Checker: no meshes with UVs found, rendering scene as-is")
        else:
            if style == "color_grid":
                grid_img = load_color_grid_image(log=rv.log)

            original_material_groups = _group_objects_by_material(uv_mesh_objects, require_basecolor=True, log=rv.log)
            rv.log(f"UV Checker: {len(original_material_groups)} material group(s) detected: "
                + ", ".join(f"{k}({sum(1 for _ in v)})" for k, v in original_material_groups))

            if enable_seam_overlay:
                rv.timer_start("bake_seams")
                for obj in uv_mesh_objects:
                    uv_img = bake_seam_overlay_to_image(obj, size=(1024, 1024), log=rv.log)
                    if uv_img:
                        uv_layout_images[obj.name] = uv_img
                rv.timer_end("bake_seams")

            for obj in uv_mesh_objects:
                mat = create_per_mesh_material(
                    obj,
                    uv_layout_images.get(obj.name),
                    grid_img=grid_img,
                    checker_scale=scale if style == "checker" else None,
                )
                obj.data.materials.clear()
                obj.data.materials.append(mat)

            rv.log(f"UV Checker: applied per-mesh materials to {len(uv_mesh_objects)} mesh(es)")

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
            else:
                # UV checker doesn't need high-quality AA, use minimum samples for speed
                scene.eevee.taa_render_samples = 1

        rv.setup_white_world(scene)

        # scene.view_settings.view_transform = 'Standard'
        # scene.view_settings.look = 'None'
        # rv.log("UV Checker: view transform set to Standard")

        if not mesh_objects:
            rv.log("UV Checker: no mesh objects found")
            return

        center, bbox_size = rv.get_bounding_box_evaluated(bpy, mesh_objects)
        rv.setup_camera(scene, center, bbox_size, render.resolution_x, render.resolution_y)

        rv.timer_start("render")
        rv.render_multi_view(bpy, scene, rv.setup_camera, center, bbox_size, opts, config, "UV Checker")
        rv.timer_end("render")

        if uv_mesh_objects and export_uv_layout and original_material_groups:
            rv.timer_start("uv_layout_composite")
            uv_composite_path = os.path.join(output_dir, f"{base_name}_uv_layout.png")
            export_uv_layout_composite_grouped(original_material_groups, uv_composite_path, cell_size=512, log=rv.log)
            rv.timer_end("uv_layout_composite")

        if uv_mesh_objects and export_blender_uv and original_material_groups:
            rv.timer_start("blender_uv_export")
            try:
                blender_uv_path = os.path.join(output_dir, f"{base_name}_blender_uv_layout.png")
                export_blender_uv_layout_composite_grouped(
                    original_material_groups,
                    blender_uv_path,
                    uv_layout_images,
                    cell_size=2048,
                    log=rv.log,
                )
            except Exception as e:
                rv.log(f"UV Checker: Blender UV export failed - {e} (requires foreground mode)")
            rv.timer_end("blender_uv_export")

        for img in uv_layout_images.values():
            bpy.data.images.remove(img)

        rv.timer_end("total")
        rv.log("UV Checker: completed successfully")
    except Exception as e:
        rv.log(f"UV Checker: ERROR - {e}")
        import traceback
        rv.log(traceback.format_exc())
        raise
    finally:
        rv.close_log()
        # Foreground mode: quit Blender automatically so the process doesn't hang
        if config.get("foreground", False):
            bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    main()
