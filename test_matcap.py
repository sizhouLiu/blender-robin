import bpy
import os

def render_matcap(output_path, matcap_name="clay_brown.exr"):
    scene = bpy.context.scene

    if not scene.camera:
        bpy.ops.object.camera_add(location=(5, -5, 5), rotation=(1.1, 0, 0.78))
        scene.camera = bpy.context.object
        print("未发现相机，已创建默认相机。")

    scene.render.engine = 'BLENDER_WORKBENCH'

    shading = scene.display.shading
    shading.light = 'MATCAP'

    try:
        shading.studio_light = matcap_name
    except:
        print(f"找不到 Matcap: {matcap_name}")

    shading.color_type = 'MATERIAL'

    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = os.path.abspath(bpy.path.abspath(output_path))
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080

    print(f"engine={scene.render.engine}, light={shading.light}, color_type={shading.color_type}, studio_light={shading.studio_light}")
    print(f"正在开始渲染至: {scene.render.filepath}")

    ret = bpy.ops.render.render(write_still=True)
    print(f"bpy.ops.render.render returned: {ret}")
    print("渲染完成！")

render_matcap("D:/test_matcap_output.png", "clay_brown.exr")