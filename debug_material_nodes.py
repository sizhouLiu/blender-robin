"""
Debug script: run inside Blender after importing the GLB.
Prints the node tree structure for all materials.
"""
import bpy

for mat in bpy.data.materials:
    print(f"\n=== Material: {mat.name} ===")
    if not mat.use_nodes:
        print("  (no nodes)")
        continue

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    print(f"  Nodes ({len(nodes)}):")
    for node in nodes:
        print(f"    - {node.type}: {node.name}")
        if node.type == 'TEX_IMAGE':
            print(f"        image: {node.image.name if node.image else 'None'}")
        if node.type == 'BSDF_PRINCIPLED':
            bc = node.inputs.get('Base Color')
            if bc and bc.links:
                from_node = bc.links[0].from_node
                print(f"        Base Color <- {from_node.type}: {from_node.name}")
            else:
                print(f"        Base Color: {bc.default_value if bc else 'N/A'}")
        if node.type == 'EMISSION':
            color = node.inputs.get('Color')
            if color and color.links:
                from_node = color.links[0].from_node
                print(f"        Color <- {from_node.type}: {from_node.name}")
            else:
                print(f"        Color: {color.default_value if color else 'N/A'}")

    print(f"  Links ({len(links)}):")
    for link in links:
        print(f"    {link.from_node.name}.{link.from_socket.name} -> {link.to_node.name}.{link.to_socket.name}")
