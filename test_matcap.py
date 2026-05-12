"""List available MatCap files in Blender 5.x."""
import bpy, os

blender_dir = os.path.dirname(bpy.app.binary_path)
for root, dirs, files in os.walk(blender_dir):
    if 'matcap' in root.lower():
        for f in files:
            print(f)

bpy.ops.wm.quit_blender()
