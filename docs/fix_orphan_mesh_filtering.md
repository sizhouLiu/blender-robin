# GLB 孤立网格过滤修复文档

## 问题描述

部分 GLB 模型（如 `fb919b3d262b40958449d7f3ccad3ab8.glb`）在 Blender 中导入后，场景中会包含**不属于实际模型的孤立网格对象**（如 `Icosphere`）。这些孤立网格会严重干扰归一化和相机定位逻辑，导致渲染结果为空白/全黑。

## 根因分析

### GLB 文件结构

问题模型的场景层级如下：

```
Scene
├── Icosphere          (type=MESH, parent=None, scale=1.0)  ← 孤立网格
└── Armature           (type=ARMATURE, parent=None, scale=0.01)
    └── ts_bot201      (type=EMPTY, scale=1.0)
        ├── ts_bot201_body_0   (type=MESH)  ← 实际模型
        ├── ts_bot201_face_0   (type=MESH)  ← 实际模型
        └── ts_bot201_hair_0   (type=MESH)  ← 实际模型
```

### 问题链路

1. **归一化阶段**：`normalize_model()` 遍历所有 `type == "MESH"` 的对象计算包围盒
2. `Icosphere` 的世界坐标范围约为 `[-1.0, 1.0]`，而实际模型因嵌套 `scale=0.01`，世界坐标仅为 `[0.001, 0.02]`
3. 计算出的 `max_dim ≈ 2.0`，`target_size = 2.0`，所以 `scale_factor ≈ 1.0`（几乎不缩放）
4. **相机定位阶段**：相机根据 `bbox_size ≈ 2.0` 定位，但实际模型只有 `0.02` 大小
5. **结果**：模型在画面中只是一个几乎不可见的小点

### 正确行为

过滤掉 `Icosphere` 后：
- 实际模型 `max_dim = 0.0179`
- `scale_factor = 111.4259`
- 模型被正确缩放到 2.0，相机正确对准

## 解决方案

### 新增函数 `_get_model_mesh_objects(bpy)`

位置：`blender_robin/blender_scripts/render_views.py`

```python
def _get_model_mesh_objects(bpy):
    """
    返回属于实际模型的网格对象，过滤掉孤立的辅助网格。
    策略：如果存在有父对象的网格，则只返回这些网格（它们是模型层级的一部分）；
    如果所有网格都是根对象，则全部返回。
    """
    all_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not all_meshes:
        return []

    parented_meshes = [obj for obj in all_meshes if obj.parent is not None]

    if parented_meshes:
        return parented_meshes

    return all_meshes
```

### 过滤逻辑

| 场景情况 | 行为 |
|---------|------|
| 存在有父对象的网格 | 只返回有父对象的网格（孤立根网格被排除） |
| 所有网格都是根对象 | 返回全部网格（兼容简单模型） |

### 修改的文件

| 文件 | 修改内容 |
|------|---------|
| `render_views.py` | 新增 `_get_model_mesh_objects()` 函数；`normalize_model()` 和 closeup 部分使用该函数 |
| `rgb_closeup.py` | `mesh_objects` 改为 `rv._get_model_mesh_objects(bpy)` |
| `clay.py` | 同上 |
| `albedo.py` | 同上 |
| `normal_map.py` | 同上 |
| `wireframe.py` | 同上 |

### 修改前后对比

```python
# 修改前 — 包含所有网格（含孤立对象）
mesh_objects = [obj for obj in scene.objects if obj.type == "MESH"]

# 修改后 — 只包含实际模型网格
mesh_objects = rv._get_model_mesh_objects(bpy)
```

## 验证结果

测试模型：`fb919b3d262b40958449d7f3ccad3ab8.glb`

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 检测到的网格数 | 4（含 Icosphere） | 3（仅模型网格） |
| max_dim | ~2.0 | 0.0179 |
| scale_factor | ~1.0 | 111.4259 |
| 归一化后 bbox | 不准确 | (0.64, 0.57, 2.00) |
| 渲染结果 | 全黑/空白 | 模型正确显示 |

## 适用范围

此修复对以下来源的 GLB 文件特别有效：
- Sketchfab 下载的带骨骼动画模型
- 包含辅助几何体（参考球、灯光代理等）的模型
- 具有深层嵌套层级且中间节点带有非单位缩放的模型
