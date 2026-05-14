# 渲染模式说明 (Render Modes)

所有渲染脚本都在 `blender_robin/blender_scripts/` 目录下，通过 `blender --background --python <script>.py -- <json_config>` 调用。每个脚本都会：

1. 导入 GLB/GLTF 模型
2. 调用 `normalize_model()` 归一化
3. 配置材质和引擎
4. 调用 `render_multi_view()` 渲染多视角

---

## RGB 渲染 (`rgb_closeup.py`)

**用途**：渲染模型的原始材质颜色，支持全身视角和随机特写。

**引擎**：EEVEE（默认）或 Cycles

**材质**：保留模型原始材质，不做替换

**环境光**：
- 优先使用 `hdri_path` 指定的 HDRI 环境贴图
- 无 HDRI 时使用白色环境光 `setup_white_world()`

**输出**：RGBA PNG，背景透明（`film_transparent = True`）

**配置参数**：
```json
{
  "script_options": {
    "glb_file": "model.glb",
    "hdri_path": "/path/to/hdri/",
    "env_texture": "kloofendal_overcast_puresky_1k.exr",
    "views": ["diagonal", "front"],
    "closeup_count": 2
  }
}
```

---

## 白模渲染 (`clay.py`)

**用途**：渲染统一灰色材质的白模，用于检查模型形态和拓扑。

**引擎**：Workbench

**材质**：替换所有网格材质为灰色（`diffuse_color = (0.82, 0.82, 0.82, 1.0)`）

**着色方式**：MatCap（`basic_1.exr`），Workbench 只读取 `mat.diffuse_color`，不需要节点树

**环境光**：白色环境光（`setup_white_world()`）

**输出**：RGB PNG（无透明通道）

**配置参数**：
```json
{
  "script_options": {
    "glb_file": "model.glb",
    "matcap": "basic_1.exr"
  }
}
```

---

## 法线图渲染 (`normal_map.py`)

**用途**：渲染表面法线方向的可视化图，用于检查法线质量。

**引擎**：Workbench

**着色方式**：MatCap `check_normal+y.exr`，将法线方向映射为颜色

**可选平面着色**：`flat_shading: true`（默认开启），每个多边形显示统一法线颜色

**输出**：RGBA PNG，背景透明

**配置参数**：
```json
{
  "script_options": {
    "glb_file": "model.glb",
    "flat_shading": true,
    "show_wireframe": false
  }
}
```

---

## 线框渲染 (`wireframe.py`)

**用途**：渲染模型的拓扑线框，支持多种视觉风格。

**引擎**：EEVEE（所有模式）

**环境光**：白色环境光（`setup_white_world()`），所有模式统一

**线框粗细**：通过 `wire_size` 参数控制（像素单位，默认 1.5px）

### 子模式（`wireframe_mode`）

#### `material`（默认）
白色 Diffuse 底色 + 黑色线框，使用 Shader 节点中的 **Wireframe 节点**（像素大小）。

节点链：
```
Wireframe Node → MixShader
  ├── [0] White Diffuse BSDF
  └── [1] Black Diffuse BSDF
```

#### `clay`
MatCap `basic_1.exr` 底色 + 黑色线框，使用 Wireframe 节点。

节点链：
```
Geometry Normal → CameraSpace Transform → UV → MatCap Texture → Emission
Wireframe Node → MixShader
  ├── [0] MatCap Emission
  └── [1] Black Emission
```

#### `normal`
法线颜色底色 + 黑色线框，使用 Wireframe 节点。效果类似 `check_normal+y.exr` MatCap。

节点链：
```
Geometry Normal → CameraSpace Transform → UV → check_normal+y.exr → Emission
Wireframe Node → MixShader
  ├── [0] Normal MatCap Emission
  └── [1] Black Emission
```

应用平面着色（`apply_flat_shading()`），每个多边形显示统一法线颜色。

#### `face_normal`
世界空间法线颜色底色 + 黑色线框。法线向量从 [-1,1] 重映射到 [0,1] 作为 RGB 颜色。

节点链：
```
Geometry Normal → VectorMath(ADD +1) → VectorMath(SCALE ×0.5) → Emission
Wireframe Node → MixShader
  ├── [0] Normal Emission
  └── [1] Black Emission
```

**配置参数**：
```json
{
  "wireframe_mode": "normal",
  "script_options": {
    "glb_file": "model.glb",
    "wireframe_mode": "normal",
    "wire_size": 1.5
  }
}
```

---

## UV 检查渲染 (`uv_checker_glb.py` / `uv_checker.py`)

**用途**：渲染 UV 展开检查图，用于验证 UV 布局和接缝。

**引擎**：EEVEE

**材质**：替换所有有 UV 的网格材质，无 UV 的网格跳过

**环境光**：白色环境光

### 子模式（`style`）

#### `color_grid`（默认）
程序化生成 2048×2048 彩色格子贴图，每个格子有：
- 黄金角度算法生成的唯一颜色（256 种）
- 2px 深色边框
- 十字准星
- 十六进制坐标标签（如 `3B` = 第 3 行第 B 列）
- L 形方向标记

#### `checker`
黑白棋盘格，通过 Blender 内置 Checker Texture 节点生成，`scale` 参数控制格子密度（默认 8.0）。

**配置参数**：
```json
{
  "script_options": {
    "glb_file": "model.glb",
    "style": "color_grid",
    "scale": 8.0
  }
}
```

---

## Albedo 渲染 (`albedo.py`)

**用途**：渲染纯材质漫反射颜色（不含光照），用于提取 Base Color 贴图。

**引擎**：EEVEE

**实现方式**：通过 Compositor 的 **DiffCol（Diffuse Color）Pass** 提取漫反射颜色，绕过光照计算。

**Compositor 节点链**：
```
RenderLayers.DiffCol → SetAlpha(alpha=RenderLayers.Alpha) → Composite
```

**环境光**：白色环境光（对 DiffCol pass 无影响，但保持一致性）

**输出**：RGBA PNG，Alpha 通道来自原始渲染的 Alpha

**配置参数**：
```json
{
  "script_options": {
    "glb_file": "model.glb",
    "hdri_path": "/path/to/hdri/"
  }
}
```

---

## 多视角渲染公共逻辑 (`render_views.py` → `render_multi_view`)

所有渲染脚本都通过 `render_multi_view()` 输出多视角图像。

### 视角列表（`views`）

| 视角名 | 相机类型 | 说明 |
|--------|----------|------|
| `diagonal` | 透视 | 斜前方 (1, -1, 0.6) 方向，默认视角 |
| `diagonal_back` | 透视 | 斜后方 (-1, 1, 0.6) 方向 |
| `front` | 正交 | 正前方 (0, -1, 0) |
| `back` | 正交 | 正后方 (0, 1, 0) |
| `left` | 正交 | 正左方 (-1, 0, 0) |
| `right` | 正交 | 正右方 (1, 0, 0) |
| `top` | 正交 | 正上方 (0, 0, 1) |
| `bottom` | 正交 | 正下方 (0, 0, -1) |
| `fixed_4view` | 透视 | 球面上 45°/135°/225°/315° 四个方位角，仰角 10° |

### 特写（Closeup）

`closeup_count` 控制随机特写数量。算法：
1. 收集所有网格顶点的世界坐标
2. 过滤掉包围盒边缘 20% 的顶点（避免拍到边缘空白）
3. 随机选取顶点作为焦点，保证相邻特写之间距离 ≥ `bbox_diagonal × 8%`
4. 以焦点为中心，包围盒对角线 10% 为半径，设置相机

### 合图（Composite）

`composite: true` 时，将所有视角图拼合为 4 列的网格图，输出为 `<base_name>_all.png`。
