"""
Blender script for UV checker/grid rendering.
Runs INSIDE Blender's Python interpreter.
Invoked via: blender --background file.blend --python uv_checker.py -- <json_config>
"""
import json
import sys


def create_color_grid_material():
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

    img = bpy.data.images.new(
        name="UV_Test_Grid", width=1024, height=1024,
        generated_type="COLOR_GRID",
    )

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


def ensure_lighting(scene):
    import bpy
    import mathutils

    has_light = any(obj.type == "LIGHT" for obj in scene.objects)
    if has_light:
        return

    light_data = bpy.data.lights.new(name="UV_Check_Sun", type="SUN")
    light_data.energy = 3.0
    light_obj = bpy.data.objects.new("UV_Check_Sun", light_data)
    light_obj.rotation_euler = mathutils.Euler((0.8, 0.2, 0.5))
    scene.collection.objects.link(light_obj)


def main() -> None:
    import bpy

    separator_idx = sys.argv.index("--")
    config_json = sys.argv[separator_idx + 1]
    config = json.loads(config_json)
    opts = config.get("script_options", {})

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

    render.engine = config.get("engine", "BLENDER_EEVEE_NEXT")
    render.resolution_x = config.get("resolution_x", 1920)
    render.resolution_y = config.get("resolution_y", 1080)
    render.resolution_percentage = config.get("resolution_percentage", 100)

    fmt = config.get("output_format", "PNG")
    render.image_settings.file_format = fmt

    output_dir = config.get("output_dir", "./uv_check_output")
    filename_pattern = config.get("filename_pattern", "uv_check")
    render.filepath = f"{output_dir}/{filename_pattern}"

    if render.engine == "BLENDER_EEVEE_NEXT":
        scene.eevee.taa_render_samples = config.get("samples", 32)

    ensure_lighting(scene)

    scene.frame_set(1)
    bpy.ops.render.render(write_still=True)
    print(f"UV Checker: rendered to {render.filepath}")


if __name__ == "__main__":
    main()
