# 模型归一化 (Model Normalization)

## 概述

归一化将导入的 GLB/GLTF 模型统一缩放到标准尺寸（默认 2.0 单位），并居中到世界原点。这确保不同尺寸的模型在渲染时具有一致的相机距离和视野。

## 实现位置

`blender_robin/blender_scripts/render_views.py` → `normalize_model(bpy, target_size=2.0)`

## 工作流程

### 1. 使用 Evaluated Depsgraph 计算包围盒

```python
depsgraph = bpy.context.evaluated_depsgraph_get()
for obj in mesh_objects:
    obj_eval = obj.evaluated_get(depsgraph)
    mesh_eval = obj_eval.to_mesh()
```

**关键点**：`evaluated_get(depsgraph)` 返回经过所有修改器（Armature、Shape Keys、Subdivision 等）计算后的最终网格。对于骨骼动画模型，这意味着顶点位置是骨骼驱动变形后的实际位置，而不是 rest pose 的原始位置。

### 2. 计算世界空间包围盒

```python
for v in mesh_eval.vertices:
    world_co = mat @ v.co  # 顶点局部坐标 → 世界坐标
    min_co.x = min(min_co.x, world_co.x)
    max_co.x = max(max_co.x, world_co.x)
    # ... y, z 同理
```

遍历所有网格对象的所有顶点，计算世界空间的 AABB（轴对齐包围盒）。

### 3. 计算缩放比例

```python
center = (min_co + max_co) / 2
bbox_size = max_co - min_co
max_dim = max(bbox_size.x, bbox_size.y, bbox_size.z)
scale_factor = target_size / max_dim
```

- `center`：包围盒中心点
- `max_dim`：包围盒最长边
- `scale_factor`：缩放比例，使最长边等于 `target_size`（默认 2.0）

### 4. 变换根对象

```python
root_objects = [obj for obj in bpy.context.scene.objects if obj.parent is None]
for obj in root_objects:
    obj.location = (obj.location - center) * scale_factor
    obj.scale *= scale_factor
```

**只操作根对象**（`parent is None`），子对象会自动跟随父对象变换。

典型的 GLB 层级结构：
```
Armature (根对象)
  ├── Mesh_Body (子对象)
  ├── Mesh_Head (子对象)
  └── ...
```

变换 Armature 后，所有子网格和骨骼会一起平移和缩放。

### 5. 更新 Depsgraph

```python
bpy.context.view_layer.update()
depsgraph = bpy.context.evaluated_depsgraph_get()
depsgraph.update()
```

强制 Blender 重新计算依赖关系图，确保骨骼动画模型的变换正确传播到蒙皮网格。

## 骨骼动画模型的处理

### 归一化不直接操作骨骼

归一化通过缩放 Armature 对象间接影响骨骼：

1. **Armature 对象的 `scale` 被修改** → 骨骼的世界空间位置按比例缩放
2. **骨骼的 pose 数据不变** → 动画关键帧、约束、IK 等保持不变
3. **蒙皮网格跟随骨骼变换** → Armature modifier 自动处理

### 当前帧姿态的影响

归一化在**当前帧**（通常是导入后的默认帧，如 frame 1 或 rest pose）计算包围盒。如果模型在其他帧有更"展开"的姿态（如手臂伸展、腿张开），可能导致：

- **问题**：渲染目标帧时，模型超出相机视野
- **解决方案**：在 `render_multi_view` 开始时，先 `scene.frame_set(animation_frame)` 切换到目标帧，然后重新计算包围盒和设置相机（已在最新代码中实现）

## 示例

导入一个高 10 米的角色模型：

1. **计算包围盒**：`max_dim = 10.0`
2. **计算缩放比例**：`scale_factor = 2.0 / 10.0 = 0.2`
3. **变换 Armature**：
   - `location = (location - center) * 0.2` → 居中到原点
   - `scale *= 0.2` → 缩放到 2.0 单位高
4. **结果**：模型高度变为 2.0 单位，中心在世界原点

## 注意事项

- **target_size = 2.0**：这是一个经验值，确保模型在默认相机距离下填充大部分视野
- **只在导入后执行一次**：归一化是破坏性操作，不应重复执行
- **保留动画数据**：骨骼动画、形态键、约束等不受影响
- **多根对象**：如果场景有多个根对象（如分离的道具），所有根对象会一起变换
