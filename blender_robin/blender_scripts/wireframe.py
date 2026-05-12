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


def setup_workbench_wireframe(opts):
    """Configure Workbench engine with white model + wireframe overlay."""
    import bpy

    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'

    shading = scene.display.shading
    shading.light = 'STUDIO'
    shading.color_type = 'SINGLE'
    shading.single_color = (0.9, 0.9, 0.9)
    shading.show_xray_wireframe = True
    shading.xray_alpha_wireframe = 0.0

    scene.render.film_transparent = True

    print("Wireframe: Workbench engine configured with wireframe overlay")


def setup_camera(scene, center, bbox_size, resolution_x, resolution_y):
    import bpy
    import mathutils

    camera = scene.camera
    if not camera:
        cam_data = bpy.data.cameras.new("Wire_Camera")
        camera = bpy.data.objects.new("Wire_Camera", cam_data)
        scene.collection.objects.link(camera)
        scene.camera = camera

    cam_data = camera.data
    cam_data.clip_start = 0.01
    cam_data.clip_end = 100000

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
    return camera


def ensure_lighting(scene):
    import bpy
    import mathutils

    has_light = any(obj.type == "LIGHT" for obj in scene.objects)
    if has_light:
        return

    light_data = bpy.data.lights.new(name="Wire_Sun", type="SUN")
    light_data.energy = 3.0
    light_obj = bpy.data.objects.new("Wire_Sun", light_data)
    light_obj.rotation_euler = mathutils.Euler((0.8, 0.2, 0.5))
    scene.collection.objects.link(light_obj)

    fill_data = bpy.data.lights.new(name="Wire_Fill", type="SUN")
    fill_data.energy = 1.5
    fill_obj = bpy.data.objects.new("Wire_Fill", fill_data)
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

    if wireframe_mode == "workbench":
        # Workbench engine: white model + wireframe overlay
        setup_workbench_wireframe(opts)
    else:
        # Material mode: shader-based wireframe on white clay
        engine = config.get("engine", "BLENDER_EEVEE_NEXT")
        render.engine = resolve_engine(engine)

        if render.engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
            samples = config.get("samples")
            if samples is not None:
                scene.eevee.taa_render_samples = samples

        wire_size = opts.get("wire_size", 1.5)
        material = create_wireframe_material(wire_size)
        apply_material_to_meshes(material)

        # Gray background
        world = scene.world
        if not world:
            world = bpy.data.worlds.new("Wire_World")
            scene.world = world
        world.use_nodes = True
        bg = world.node_tree.nodes.get("Background")
        if bg:
            bg.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1.0)
            bg.inputs["Strength"].default_value = 1.0

        ensure_lighting(scene)

    mesh_objects = rv._get_model_mesh_objects(bpy)
    if not mesh_objects:
        print("Wireframe: no mesh objects found")
        return

    center, bbox_size = rv.get_bounding_box_evaluated(bpy, mesh_objects)
    setup_camera(scene, center, bbox_size, render.resolution_x, render.resolution_y)

    rv.render_multi_view(bpy, scene, setup_camera, center, bbox_size, opts, config, "Wireframe")


if __name__ == "__main__":
    main()
