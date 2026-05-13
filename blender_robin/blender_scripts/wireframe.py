"""
Blender script for wireframe rendering from GLB/GLTF files.
Runs INSIDE Blender's Python interpreter.
Invoked via: blender --background --python wireframe.py -- <json_config>

Supports two modes via script_options.wireframe_mode:
  - "material" (default): White clay material with black wireframe overlay (shader-based)
  - "workbench": Workbench engine with wireframe overlay on white model
"""
import json
import math
import sys


def import_glb(filepath):
    import bpy

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    bpy.ops.import_scene.gltf(filepath=filepath)
    print(f"Wireframe: imported {filepath}")


def create_wireframe_material(wire_size=1.5):
    """White base + black wireframe overlay using Wireframe node."""
    import bpy

    mat = bpy.data.materials.new(name="Wireframe_White")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (600, 0)

    white_bsdf = nodes.new("ShaderNodeBsdfDiffuse")
    white_bsdf.inputs["Color"].default_value = (0.9, 0.9, 0.9, 1.0)
    white_bsdf.location = (0, 100)

    wire_bsdf = nodes.new("ShaderNodeBsdfDiffuse")
    wire_bsdf.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    wire_bsdf.location = (0, -100)

    wireframe = nodes.new("ShaderNodeWireframe")
    wireframe.inputs["Size"].default_value = wire_size
    wireframe.use_pixel_size = True
    wireframe.location = (-200, -200)

    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (300, 0)

    links.new(wireframe.outputs["Fac"], mix.inputs["Fac"])
    links.new(white_bsdf.outputs["BSDF"], mix.inputs[1])
    links.new(wire_bsdf.outputs["BSDF"], mix.inputs[2])
    links.new(mix.outputs["Shader"], output.inputs["Surface"])

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

    print(f"Wireframe: applied material to {applied} mesh(es)")
    return applied


def apply_flat_shading():
    """Apply flat shading to all mesh objects."""
    import bpy

    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH':
            for poly in obj.data.polygons:
                poly.use_smooth = False
            obj.data.update()

    print("Wireframe: applied flat shading")


def _load_matcap_image(bpy, matcap_name):
    """Search Blender's installation for a MatCap .exr file and load it."""
    import os

    img = bpy.data.images.get(matcap_name)
    if img:
        return img

    blender_dir = os.path.dirname(bpy.app.binary_path)
    for root, dirs, files in os.walk(blender_dir):
        if matcap_name in files:
            path = os.path.join(root, matcap_name)
            img = bpy.data.images.load(path)
            print(f"Wireframe: Loaded MatCap from {path}")
            return img

    print(f"Wireframe: MatCap '{matcap_name}' not found in Blender installation")
    return None


def _build_matcap_emission_nodes(nodes, links, img):
    """Build camera-space normal → UV → MatCap texture → Emission node chain.
    Returns the matcap_emission node.
    """
    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.location = (-600, -50)

    vector_transform = nodes.new("ShaderNodeVectorTransform")
    vector_transform.vector_type = 'NORMAL'
    vector_transform.convert_from = 'WORLD'
    vector_transform.convert_to = 'CAMERA'
    vector_transform.location = (-400, -50)

    separate_xyz = nodes.new("ShaderNodeSeparateXYZ")
    separate_xyz.location = (-200, -50)

    math_add_x = nodes.new("ShaderNodeMath")
    math_add_x.operation = 'ADD'
    math_add_x.inputs[1].default_value = 1.0
    math_add_x.location = (0, 50)

    math_scale_x = nodes.new("ShaderNodeMath")
    math_scale_x.operation = 'MULTIPLY'
    math_scale_x.inputs[1].default_value = 0.5
    math_scale_x.location = (150, 50)

    math_add_y = nodes.new("ShaderNodeMath")
    math_add_y.operation = 'ADD'
    math_add_y.inputs[1].default_value = 1.0
    math_add_y.location = (0, -50)

    math_scale_y = nodes.new("ShaderNodeMath")
    math_scale_y.operation = 'MULTIPLY'
    math_scale_y.inputs[1].default_value = 0.5
    math_scale_y.location = (150, -50)

    combine_xy = nodes.new("ShaderNodeCombineXYZ")
    combine_xy.location = (300, 0)

    img_tex = nodes.new("ShaderNodeTexImage")
    img_tex.image = img
    img_tex.location = (450, 100)

    matcap_emission = nodes.new("ShaderNodeEmission")
    matcap_emission.location = (650, 100)

    links.new(geometry.outputs["Normal"], vector_transform.inputs["Vector"])
    links.new(vector_transform.outputs["Vector"], separate_xyz.inputs["Vector"])
    links.new(separate_xyz.outputs["X"], math_add_x.inputs[0])
    links.new(math_add_x.outputs["Value"], math_scale_x.inputs[0])
    links.new(separate_xyz.outputs["Y"], math_add_y.inputs[0])
    links.new(math_add_y.outputs["Value"], math_scale_y.inputs[0])
    links.new(math_scale_x.outputs["Value"], combine_xy.inputs["X"])
    links.new(math_scale_y.outputs["Value"], combine_xy.inputs["Y"])
    links.new(combine_xy.outputs["Vector"], img_tex.inputs["Vector"])
    links.new(img_tex.outputs["Color"], matcap_emission.inputs["Color"])

    return matcap_emission


def create_matcap_wireframe_material(wire_size=1.5, matcap_name="basic_1.exr"):
    """Create EEVEE material: MatCap texture sampled via camera-space normals + black wireframe.

    Args:
        wire_size: Wireframe line thickness in pixels
        matcap_name: MatCap .exr filename (e.g. 'basic_1.exr', 'check_normal+y.exr')
    """
    import bpy

    mat = bpy.data.materials.new(name="MatCap_Wireframe")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (800, 0)

    img = _load_matcap_image(bpy, matcap_name)

    if img:
        matcap_emission = _build_matcap_emission_nodes(nodes, links, img)
    else:
        # Fallback: flat gray emission
        matcap_emission = nodes.new("ShaderNodeEmission")
        matcap_emission.inputs["Color"].default_value = (0.82, 0.82, 0.82, 1.0)
        matcap_emission.location = (200, 100)

    # Black emission for wireframe
    wire_emission = nodes.new("ShaderNodeEmission")
    wire_emission.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    wire_emission.location = (200, -250)

    # Wireframe node
    wireframe = nodes.new("ShaderNodeWireframe")
    wireframe.inputs["Size"].default_value = wire_size
    wireframe.use_pixel_size = True
    wireframe.location = (0, -350)

    # Mix shader
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (850, 0)

    # Connect
    links.new(wireframe.outputs["Fac"], mix.inputs["Fac"])
    links.new(matcap_emission.outputs["Emission"], mix.inputs[1])
    links.new(wire_emission.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], output.inputs["Surface"])

    return mat
    """Create material that colors faces by world-space normal + black wireframe overlay."""
    import bpy

    mat = bpy.data.materials.new(name="FaceNormal_Wireframe")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Output node
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (800, 0)

    # Geometry node to get world-space normal
    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.location = (-400, 100)

    # Vector Math nodes to remap normal from [-1,1] to [0,1] for RGB
    # Formula: RGB = (Normal + 1) / 2
    vector_add = nodes.new("ShaderNodeVectorMath")
    vector_add.operation = 'ADD'
    vector_add.inputs[1].default_value = (1.0, 1.0, 1.0)
    vector_add.location = (-200, 100)

    vector_scale = nodes.new("ShaderNodeVectorMath")
    vector_scale.operation = 'SCALE'
    vector_scale.inputs['Scale'].default_value = 0.5
    vector_scale.location = (0, 100)

    # Emission shader for face normal color (unaffected by lighting)
    normal_emission = nodes.new("ShaderNodeEmission")
    normal_emission.location = (200, 100)

    # Black emission for wireframe
    wire_emission = nodes.new("ShaderNodeEmission")
    wire_emission.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    wire_emission.location = (200, -100)

    # Wireframe node
    wireframe = nodes.new("ShaderNodeWireframe")
    wireframe.inputs["Size"].default_value = wire_size
    wireframe.use_pixel_size = True
    wireframe.location = (0, -200)

    # Mix shader
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (500, 0)

    # Connect nodes
    links.new(geometry.outputs["Normal"], vector_add.inputs[0])
    links.new(vector_add.outputs["Vector"], vector_scale.inputs[0])
    links.new(vector_scale.outputs["Vector"], normal_emission.inputs["Color"])

    links.new(wireframe.outputs["Fac"], mix.inputs["Fac"])
    links.new(normal_emission.outputs["Emission"], mix.inputs[1])
    links.new(wire_emission.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], output.inputs["Surface"])

    return mat


def setup_workbench_wireframe(opts, matcap_name=None):
    """Configure Workbench engine with model + wireframe overlay."""
    import bpy

    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'

    shading = scene.display.shading

    if matcap_name:
        # Use MatCap shading (for clay/normal modes)
        shading.light = 'MATCAP'
        shading.color_type = 'MATERIAL'
        try:
            shading.studio_light = matcap_name
            print(f"Wireframe: Using MatCap {matcap_name}")
        except Exception:
            print(f"Wireframe: MatCap '{matcap_name}' not found, using default")
    else:
        # Use solid color shading (for basic wireframe)
        shading.light = 'STUDIO'
        shading.color_type = 'SINGLE'
        shading.single_color = (0.9, 0.9, 0.9)

    # Enable wireframe overlay
    shading.show_xray_wireframe = True
    shading.xray_alpha_wireframe = 0.0  # Opaque wireframe

    scene.render.film_transparent = True

    print("Wireframe: Workbench engine configured with wireframe overlay")


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
        print("Wireframe: Warning - no glb_file specified")
        return

    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "render_views", os.path.join(os.path.dirname(__file__), "render_views.py"))
    rv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rv)
    rv.normalize_model(bpy)

    scene = bpy.context.scene
    render = scene.render

    render.resolution_x = config.get("resolution_x", 1920)
    render.resolution_y = config.get("resolution_y", 1080)
    render.resolution_percentage = config.get("resolution_percentage", 100)

    fmt = config.get("output_format", "PNG")
    render.image_settings.file_format = fmt
    render.image_settings.color_mode = 'RGBA'
    render.film_transparent = True

    wireframe_mode = opts.get("wireframe_mode", "material")
    wire_size = opts.get("wire_size", 1.5)

    engine = config.get("engine", "BLENDER_EEVEE_NEXT")
    render.engine = rv.resolve_engine(engine)
    if render.engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        samples = config.get("samples")
        if samples is not None:
            scene.eevee.taa_render_samples = samples

    if wireframe_mode == "clay":
        # EEVEE: basic_1.exr MatCap + black wireframe
        apply_flat_shading()
        material = create_matcap_wireframe_material(wire_size, matcap_name="basic_1.exr")
        apply_material_to_meshes(material)
    elif wireframe_mode == "normal":
        # EEVEE: check_normal+y.exr MatCap + black wireframe
        apply_flat_shading()
        material = create_matcap_wireframe_material(wire_size, matcap_name="check_normal+y.exr")
        apply_material_to_meshes(material)
    elif wireframe_mode == "face_normal":
        # EEVEE: world-space normal colors + black wireframe
        apply_flat_shading()
        material = create_face_normal_wireframe_material(wire_size)
        apply_material_to_meshes(material)
    else:
        # material mode: white clay + shader wireframe
        material = create_wireframe_material(wire_size)
        apply_material_to_meshes(material)

    world = scene.world
    if not world:
        world = bpy.data.worlds.new("Wire_World")
        scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1.0)
        bg.inputs["Strength"].default_value = 1.0

    mesh_objects = rv._get_model_mesh_objects(bpy)
    if not mesh_objects:
        print("Wireframe: no mesh objects found")
        return

    center, bbox_size = rv.get_bounding_box_evaluated(bpy, mesh_objects)
    rv.setup_camera(scene, center, bbox_size, render.resolution_x, render.resolution_y)

    rv.render_multi_view(bpy, scene, rv.setup_camera, center, bbox_size, opts, config, "Wireframe")


if __name__ == "__main__":
    main()
