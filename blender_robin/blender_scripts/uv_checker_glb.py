"""
Blender script for UV checker rendering from GLB/GLTF files.
Runs INSIDE Blender's Python interpreter.
Invoked via: blender --background --python uv_checker_glb.py -- <json_config>
"""
import json
import sys


def import_glb(filepath):
    import bpy

    # Clear default scene objects (cube, light, camera)
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    bpy.ops.import_scene.gltf(filepath=filepath)
    print(f"UV Checker: imported {filepath}")


def create_color_grid_material():
    import bpy
    import colorsys

    mat = bpy.data.materials.new(name="UV_Checker")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (400, 0)

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (200, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    width, height = 2048, 2048
    img = bpy.data.images.new(name="UV_Test_Grid", width=width, height=height, alpha=False)

    cell_size = 128
    grid_w = width // cell_size
    grid_h = height // cell_size

    # 3x5 bitmap font for hex digits (MSB = leftmost pixel)
    FONT = {
        '0': [0b111, 0b101, 0b101, 0b101, 0b111],
        '1': [0b010, 0b110, 0b010, 0b010, 0b111],
        '2': [0b111, 0b001, 0b111, 0b100, 0b111],
        '3': [0b111, 0b001, 0b111, 0b001, 0b111],
        '4': [0b101, 0b101, 0b111, 0b001, 0b001],
        '5': [0b111, 0b100, 0b111, 0b001, 0b111],
        '6': [0b111, 0b100, 0b111, 0b101, 0b111],
        '7': [0b111, 0b001, 0b010, 0b010, 0b010],
        '8': [0b111, 0b101, 0b111, 0b101, 0b111],
        '9': [0b111, 0b101, 0b111, 0b001, 0b111],
        'A': [0b010, 0b101, 0b111, 0b101, 0b101],
        'B': [0b110, 0b101, 0b110, 0b101, 0b110],
        'C': [0b011, 0b100, 0b100, 0b100, 0b011],
        'D': [0b110, 0b101, 0b101, 0b101, 0b110],
        'E': [0b111, 0b100, 0b110, 0b100, 0b111],
        'F': [0b111, 0b100, 0b110, 0b100, 0b100],
    }
    FONT_W, FONT_H = 3, 5
    SCALE = 3

    # Generate 256 distinct colors using golden angle for maximum hue spread
    cell_colors = []
    for i in range(grid_w * grid_h):
        hue = (i * 0.618033988749895) % 1.0
        sat = 0.5 + (i % 3) * 0.15
        val = 0.65 + (i % 2) * 0.2
        r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
        cell_colors.append((r, g, b))

    pixels = [0.0] * (width * height * 4)

    def put(px, py, r, g, b):
        if 0 <= px < width and 0 <= py < height:
            i = (py * width + px) * 4
            pixels[i] = r
            pixels[i + 1] = g
            pixels[i + 2] = b
            pixels[i + 3] = 1.0

    # Fill all cells (optimized with slice assignment)
    for row in range(grid_h):
        for col in range(grid_w):
            r, g, b = cell_colors[row * grid_w + col]
            x0 = col * cell_size
            y0 = row * cell_size
            row_data = [r, g, b, 1.0] * cell_size
            for y in range(y0, y0 + cell_size):
                start = (y * width + x0) * 4
                pixels[start:start + cell_size * 4] = row_data

    # Draw decorations on each cell
    for row in range(grid_h):
        for col in range(grid_w):
            r, g, b = cell_colors[row * grid_w + col]
            x0 = col * cell_size
            y0 = row * cell_size

            # Border (2px, darkened)
            br, bg, bb = r * 0.3, g * 0.3, b * 0.3
            for i in range(2):
                for x in range(x0, x0 + cell_size):
                    put(x, y0 + i, br, bg, bb)
                    put(x, y0 + cell_size - 1 - i, br, bg, bb)
                for y in range(y0, y0 + cell_size):
                    put(x0 + i, y, br, bg, bb)
                    put(x0 + cell_size - 1 - i, y, br, bg, bb)

            # Crosshair at center (thin +)
            cx = x0 + cell_size // 2
            cy = y0 + cell_size // 2
            cr, cg, cb = r * 0.4, g * 0.4, b * 0.4
            for i in range(-12, 13):
                put(cx + i, cy, cr, cg, cb)
                put(cx, cy + i, cr, cg, cb)

            # Text color: contrast against background
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            tr, tg, tb = (0.05, 0.05, 0.05) if lum > 0.45 else (0.95, 0.95, 0.95)

            # Draw hex label (e.g. "3B" = row 3, col B)
            label = f"{row:X}{col:X}"
            char_w_scaled = FONT_W * SCALE
            spacing = SCALE
            total_w = len(label) * char_w_scaled + (len(label) - 1) * spacing
            text_x = x0 + (cell_size - total_w) // 2
            text_y = y0 + cell_size // 2 + 10

            for ci, ch in enumerate(label):
                glyph = FONT.get(ch)
                if not glyph:
                    continue
                gx0 = text_x + ci * (char_w_scaled + spacing)
                for gy, glyph_row in enumerate(glyph):
                    for gx in range(FONT_W):
                        if glyph_row & (1 << (FONT_W - 1 - gx)):
                            for sy in range(SCALE):
                                for sx in range(SCALE):
                                    px = gx0 + gx * SCALE + sx
                                    py = text_y + (FONT_H - 1 - gy) * SCALE + sy
                                    put(px, py, tr, tg, tb)

            # L-shape direction marker (bottom-left corner of cell)
            lx = x0 + 8
            ly = y0 + 6
            for i in range(20):
                for t in range(2):
                    put(lx + t, ly + i, tr, tg, tb)
                    put(lx + i, ly + t, tr, tg, tb)

    img.pixels = pixels
    print(f"UV Checker: generated {grid_w}x{grid_h} color grid ({cell_size}px cells)")

    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.location = (-200, 0)

    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-400, 0)

    links.new(tex_coord.outputs["UV"], tex.inputs["Vector"])
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

    return mat


def create_checker_material(scale):
    import bpy

    mat = bpy.data.materials.new(name="UV_Checker")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (400, 0)

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (200, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    checker = nodes.new("ShaderNodeTexChecker")
    checker.inputs["Scale"].default_value = scale
    checker.location = (-200, 0)

    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-400, 0)

    links.new(tex_coord.outputs["UV"], checker.inputs["Vector"])
    links.new(checker.outputs["Color"], bsdf.inputs["Base Color"])

    return mat


def apply_material_to_meshes(material):
    import bpy

    applied = 0
    skipped = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        if not obj.data.uv_layers:
            skipped += 1
            print(f"UV Checker: skipping '{obj.name}' (no UV map)")
            continue
        obj.data.materials.clear()
        obj.data.materials.append(material)
        applied += 1

    print(f"UV Checker: applied to {applied} mesh(es), skipped {skipped}")
    return applied


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
        print("UV Checker: Warning - no glb_file specified in script_options")

    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "render_views", os.path.join(os.path.dirname(__file__), "render_views.py"))
    rv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rv)
    rv.normalize_model(bpy)

    style = opts.get("style", "color_grid")
    scale = opts.get("scale", 8.0)

    if style == "checker":
        material = create_checker_material(scale)
    else:
        material = create_color_grid_material()

    count = apply_material_to_meshes(material)
    if count == 0:
        print("UV Checker: no meshes with UVs found, rendering scene as-is")

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

    # Set a white world background for better visibility
    world = scene.world
    if not world:
        world = bpy.data.worlds.new("UV_Check_World")
        scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.2, 0.2, 0.2, 1.0)
        bg.inputs["Strength"].default_value = 1.0

    mesh_objects = rv._get_model_mesh_objects(bpy)
    if not mesh_objects:
        print("UV Checker: no mesh objects found")
        return

    center, bbox_size = rv.get_bounding_box_evaluated(bpy, mesh_objects)
    rv.setup_camera(scene, center, bbox_size, render.resolution_x, render.resolution_y)
    ensure_lighting(scene)

    rv.render_multi_view(bpy, scene, rv.setup_camera, center, bbox_size, opts, config, "UV Checker")


if __name__ == "__main__":
    main()
