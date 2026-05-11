"""
Blender script: import a GLB, normalize (center + scale), export as GLB.
Runs INSIDE Blender's Python interpreter.
Invoked via: blender --background --python normalize_export.py -- '<json_config>'
"""
import json
import os
import sys


def main() -> None:
    import bpy

    separator_idx = sys.argv.index("--")
    config_json = sys.argv[separator_idx + 1]
    config = json.loads(config_json)
    opts = config.get("script_options", {})

    glb_file = opts.get("glb_file")
    if not glb_file:
        print("NormalizeExport: Error - no glb_file specified")
        sys.exit(1)

    output_path = opts.get("output_path")
    if not output_path:
        print("NormalizeExport: Error - no output_path specified")
        sys.exit(1)

    target_size = opts.get("target_size", 2.0)

    # Clear default scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    # Import GLB
    bpy.ops.import_scene.gltf(filepath=glb_file)
    print(f"NormalizeExport: imported {glb_file}")

    # Load shared render_views module
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "render_views", os.path.join(os.path.dirname(__file__), "render_views.py"))
    rv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rv)

    # Normalize
    rv.normalize_model(bpy, target_size=target_size)

    # Export
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=output_path,
        export_format='GLB',
        export_apply=False,
        use_selection=False,
    )
    print(f"NormalizeExport: exported normalized model to {output_path}")
    print(f"Saved: '{output_path}'")


if __name__ == "__main__":
    main()
