"""
Blender script for wireframe-on-white rendering from GLB/GLTF files.
Runs INSIDE Blender's Python interpreter.
Invoked via: blender --background --python wireframe.py -- <json_config>
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


def create_wireframe_material():
    """White base + black wireframe overlay using Wireframe node."""
    import bpy

    mat = bpy.data.materials.new(name="Wireframe_White")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (600, 0)

    # White base shader
    white_bsdf = nodes.new("ShaderNodeBsdfDiffuse")
    white_bsdf.inputs["Color"].default_value = (0.9, 0.9, 0.9, 1.0)
    white_bsdf.location = (0, 100)

    # Black wireframe shader
    wire_bsdf = nodes.new("ShaderNodeBsdfDiffuse")
    wire_bsdf.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    wire_bsdf.location = (0, -100)

    # Wireframe node as mix factor
    wireframe = nodes.new("ShaderNodeWireframe")
    wireframe.inputs["Size"].default_value = 1.5
    wireframe.use_pixel_size = True
    wireframe.location = (-200, -200)

    # Mix: white where no wire, black on wire edges
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

    print(f"Wireframe: applied to {applied} mesh(es)")
    return applied


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

    radius = bbox_size.length / 2.0
    aspect = resolution_x / resolution_y
    fov = cam_data.angle

    if aspect >= 1.0:
        vfov = 2.0 * math.atan(math.tan(fov / 2.0) / aspect)
    else:
        vfov = fov

    half_angle = min(fov / 2.0, vfov / 2.0)
    distance = radius / math.sin(half_angle) * 1.05

    direction = mathutils.Vector((1.0, -1.0, 0.6)).normalized()
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


def setup_closeup_camera(camera, center, bbox_size, resolution_x, resolution_y):
    """Frame a closeup region, same as rgb_closeup logic."""
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

    print(f"Wireframe: closeup, bbox size {bbox_size.length:.2f}, distance {distance:.2f}")
    return camera


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

    # Create and apply wireframe material
    wire_size = opts.get("wire_size", 1.5)
    material = create_wireframe_material()
    for node in material.node_tree.nodes:
        if node.type == "WIREFRAME":
            node.inputs["Size"].default_value = wire_size
            node.use_pixel_size = True
    apply_material_to_meshes(material)

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

    # White background
    world = scene.world
    if not world:
        world = bpy.data.worlds.new("Wire_World")
        scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        bg.inputs["Strength"].default_value = 1.0

    mesh_objects = [obj for obj in scene.objects if obj.type == "MESH"]
    if not mesh_objects:
        print("Wireframe: no mesh objects found")
        return

    center, bbox_size = get_bounding_box(mesh_objects)
    camera = setup_camera(scene, center, bbox_size, render.resolution_x, render.resolution_y)
    ensure_lighting(scene)

    output_dir = config.get("output_dir", "./wireframe_output")
    base_name = config.get("filename_pattern", "render")

    # --- Render 1: Full body ---
    render.filepath = f"{output_dir}/{base_name}_full"
    scene.frame_set(1)
    bpy.ops.render.render(write_still=True)
    print(f"Wireframe: full body rendered to {render.filepath}")

    # --- Render 2: Random region closeup ---
    import random
    import mathutils

    bbox_diagonal = bbox_size.length
    closeup_ratio = 0.10
    sub_radius = bbox_diagonal * closeup_ratio / 2.0

    verts_world = []
    for obj in mesh_objects:
        mat = obj.matrix_world
        for v in obj.data.vertices:
            verts_world.append(mat @ v.co)

    if verts_world:
        focus_point = random.choice(verts_world)
    else:
        focus_point = center

    sub_bbox_size = mathutils.Vector((sub_radius * 2, sub_radius * 2, sub_radius * 2))
    print(f"Wireframe: closeup at ({focus_point.x:.2f}, {focus_point.y:.2f}, {focus_point.z:.2f})")
    setup_closeup_camera(camera, focus_point, sub_bbox_size, render.resolution_x, render.resolution_y)
    render.filepath = f"{output_dir}/{base_name}_closeup"
    bpy.ops.render.render(write_still=True)
    print(f"Wireframe: closeup rendered to {render.filepath}")


if __name__ == "__main__":
    main()
