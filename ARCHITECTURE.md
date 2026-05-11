# blender-robin 架构说明

## 整体流程

```
CLI (cli.py)
  │
  ├─ 构建 RenderConfig（script_name, script_options, views 等）
  │
  └─ BlenderRenderer.build_command(config)
        │
        └─ blender --background --python <script>.py -- '<json_config>'
                │
                └─ Blender 内部（clay.py / albedo.py / ...）
                      ├─ 解析 JSON 参数
                      ├─ 导入 GLB
                      ├─ rv.normalize_model()
                      ├─ 配置引擎 / 材质 / 灯光
                      └─ rv.render_multi_view()
                            ├─ 多视角渲染
                            ├─ 随机特写
                            └─ 合图 / 元数据导出
```

---

## 模块说明

### `blender_robin/cli.py` — 命令行入口

Click 命令组，每个渲染模式对应一条子命令：

| 命令 | 脚本 |
|---|---|
| `clay` | `clay.py` |
| `albedo` | `albedo.py` |
| `normal-map` | `normal_map.py` |
| `wireframe` | `wireframe.py` |
| `rgb-closeup` | `rgb_closeup.py` |
| `uv-check` | `uv_checker_glb.py` |

公共选项（`_common_render_options`）：`--views`、`--closeup-count`、`--no-composite`、`--delete-views`、`--hdri`、`--export-metadata`、`--format`。

---

### `blender_robin/renderer.py` — Blender 进程调用器

**`BlenderRenderer`** 类：

- `render(config)` → 启动子进程，逐行读 stdout，解析进度和输出文件路径，返回 `RenderResult`
- `_build_script_command(config)` → 构建命令：`blender --background --python <script> -- '<json>'`
- GLB/GLTF 文件不传 blend 文件路径，Blender 以空场景启动，脚本内导入模型
- Windows 下使用 `CREATE_NO_WINDOW` 标志隐藏窗口

---

### `blender_robin/config.py` — 配置数据类

`RenderConfig` 字段：

| 字段 | 说明 |
|---|---|
| `blend_file` | 输入文件路径 |
| `use_script` | True = 用 Python 脚本渲染（GLB 流程） |
| `script_name` | 脚本名称（如 `"clay.py"`） |
| `script_options` | 传入脚本的 JSON 参数（views、closeup_count 等） |
| `engine` | 渲染引擎（BLENDER_WORKBENCH / BLENDER_EEVEE_NEXT） |
| `resolution_x/y` | 输出分辨率 |

---

### `blender_robin/blender_scripts/render_views.py` — 共享渲染基础库

所有渲染脚本都动态 import 此模块（via `importlib`）。

#### 归一化

```python
rv.normalize_model(bpy, target_size=2.0)
```

1. 通过 `evaluated_depsgraph_get()` 获取骨骼变形后的实际顶点
2. 计算所有 mesh 的世界空间 AABB
3. `center = (min + max) / 2`，`scale_factor = 2.0 / max_dim`
4. 对所有根对象执行 `location -= center`，`scale *= scale_factor`

> **重要：** 使用 evaluated depsgraph，骨骼动画、shape key、modifier 的变形都能正确计入边界框。

#### 多视角渲染

```python
rv.render_multi_view(bpy, scene, setup_camera_func, center, bbox_size, opts, config, label)
```

支持的视角名称：

| 类型 | 视角 |
|---|---|
| 透视 | `diagonal`（默认斜视角）、`diagonal_back`（背面斜视角） |
| 正交 | `front`、`back`、`left`、`right`、`top`、`bottom` |
| 固定4视角 | `fixed_4view`（方位角 45/135/225/315°，仰角 10°） |

**相机距离计算：** 将 bbox 的 8 个角点投影到相机本地坐标系的右向/上向轴，取最大投影范围，按 FOV 推算所需距离，乘以 1.02（2% 留白）。

**随机特写：** 从 evaluated mesh 的顶点中随机采样，保证采样点间距 ≥ `bbox_diagonal * 0.08`，避免重复拍同一区域。

**合图：** 4 列网格，按像素拼合所有视角图（含特写），输出 `*_all.png`。

**元数据：** 输出 `meta.json`，记录相机 FOV、焦距、每帧变换矩阵，格式兼容 NeRF / 3DGS 训练。

---

### `clay.py` — 白模/灰模渲染

**引擎：** `BLENDER_WORKBENCH`

**实现方式：**

| 配置项 | 值 |
|---|---|
| `shading.light` | `MATCAP` |
| `shading.color_type` | `MATERIAL` |
| `shading.studio_light` | `basic_1.exr`（可配置） |
| `shading.background_type` | `VIEWPORT` |
| `shading.background_color` | `(0.05, 0.05, 0.05)` 近黑色 |
| 材质 | 纯灰 `diffuse_color = (0.82, 0.82, 0.82)` |

渲染完成后用 numpy 做后处理抠图：采样四角背景色，tolerance 0.05，将背景像素 alpha 设为 0，保存带透明通道的 PNG。

---

### `albedo.py` — 漫反射颜色渲染

**引擎：** `BLENDER_EEVEE_NEXT`

**实现方式：** 启用 `use_pass_diffuse_color`，通过合成器节点获取 DiffCol pass（纯材质颜色，无光照影响）。世界背景设为白色。

---

### `normal_map.py` — 法线图渲染

**引擎：** `BLENDER_EEVEE_NEXT`

**实现方式：** 启用 `use_pass_normal`，合成器中将法线 pass 从 `[-1, 1]` 线性映射到 `[0, 1]`（`× 0.5 + 0.5`）。朝向相机的平面输出经典浅蓝色 `(0.5, 0.5, 1.0)`。可选 `shade_flat()` 开启平面着色。

---

### `wireframe.py` — 线框渲染

**引擎：** `BLENDER_EEVEE_NEXT`

**实现方式：** 用 `ShaderNodeWireframe`（像素宽度，默认 1.5px）混合白色和黑色 Diffuse shader，黑线白底。添加两盏 Sun 灯保证 Eevee 正常渲染。

---

### `rgb_closeup.py` — 全彩渲染 + 特写

**引擎：** `BLENDER_EEVEE_NEXT`

**实现方式：** 保留模型原有材质，添加 Sun 灯（主光 3.0 + 补光 1.0），暗灰色世界背景 `(0.2, 0.2, 0.2)`，正常 PBR 渲染。

---

## 配置文件 `robin_config.json`

```json
{
  "blender_path": "F:\\blender\\blender.exe",
  "resolution": [1920, 1920],
  "parallel": 6,
  "views": ["diagonal", "front", "back", "left", "right", "top"],
  "closeup_count": 2,
  "composite": true,
  "uv_style": "color_grid",
  "delete_views": true,
  "export_metadata": false,
  "output_format": "PNG"
}
```

---

## 关键设计决策

1. **Blender 作为子进程**：每次渲染启动独立 Blender 进程，通过 `--python script.py -- <json>` 传参，进程间完全隔离，支持 `parallel` 并发。

2. **动态 import render_views**：每个脚本在 Blender 内部通过 `importlib` 动态加载同目录的 `render_views.py`，避免安装依赖，路径始终相对于脚本自身。

3. **evaluated depsgraph**：归一化和特写顶点采样均使用 `evaluated_get(depsgraph)`，确保骨骼动画模型的实际形态被正确计算。

4. **合图在 Blender 内完成**：用 `bpy.data.images` + numpy 拼合像素，不依赖 Pillow 等外部库。
