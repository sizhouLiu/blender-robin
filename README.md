# Blender Robin 使用文档

## 简介

Blender Robin 是一个自动化的 3D 模型渲染工具，支持批量渲染 GLB/GLTF 格式的模型文件，提供多种渲染模式。

## 安装

### 1. 安装 Blender

从 [Blender 官网](https://www.blender.org/download/) 下载并安装 Blender。

### 2. 设置 Blender 路径

**方法一：永久环境变量（推荐）**

1. 按 `Win + R`，输入 `sysdm.cpl`，回车
2. 点击"高级"选项卡 → "环境变量"
3. 在"用户变量"区域点击"新建"
4. 变量名：`BLENDER_PATH`
5. 变量值：Blender 可执行文件的完整路径（例如 `D:\Blender\blender.exe`）
6. 点击确定保存

**方法二：PowerShell 配置文件**

在 PowerShell 中运行：

```powershell
if (!(Test-Path -Path $PROFILE)) { New-Item -ItemType File -Path $PROFILE -Force }
Add-Content -Path $PROFILE -Value '$env:BLENDER_PATH = "D:\Blender\blender.exe"'
```

将路径替换为你的 Blender 安装位置。

### 3. 安装 Robin

```bash
pip install -e .
```

## 使用方式

### 交互式启动器（推荐）

最简单的使用方式，提供图形化菜单选择：

```bash
python robin_interactive.py
```

启动后会显示：

```
🎨 Robin Render Toolkit
========================

Blender: D:\Blender\blender.exe

模型文件夹路径: D:\my_models

选择渲染模式 (↑↓ 选择, Enter 确认):
  > UV 棋盘格检查
    RGB 全身 + 特写
    线框图 (全身 + 特写)
    白模渲染
    法线图
    全部渲染

分辨率 (直接回车使用 1920x1080): 
```

**操作说明：**
- 输入模型文件夹路径（支持拖拽）
- 用 ↑↓ 方向键选择渲染模式
- 按 Enter 确认
- 输入分辨率（可选，直接回车使用默认 1920x1080）

### 命令行方式

如果需要脚本化或批处理，可以直接使用命令行：

#### UV 棋盘格检查

检查模型的 UV 展开质量，每个格子显示坐标标签。

```bash
robin uv-check D:\models -o D:\output -r 1920 1080
```

#### RGB 全身 + 特写渲染

渲染模型原始材质，生成全身图和随机区域特写图。

```bash
robin rgb-closeup D:\models -o D:\output -r 1920 1080
```

#### 线框图渲染

白底黑线框，生成全身图和特写图。

```bash
robin wireframe D:\models -o D:\output -r 1920 1080
```

#### 白模渲染

纯白色材质渲染，用于查看模型形态。

```bash
robin clay D:\models -o D:\output -r 1920 1080
```

#### 法线图渲染

渲染模型表面法线，X→R、Y→G、Z→B，颜色直观反映曲面朝向。

```bash
robin normal-map D:\models -o D:\output -r 1920 1080
```



- `D:\models` - 包含 .glb/.gltf 文件的文件夹路径
- `-o D:\output` - 输出目录（可选，默认为 `模型文件夹/robin_output`）
- `-r 1920 1080` - 分辨率（可选，默认 1920x1080）

## 渲染模式详解

### 1. UV 棋盘格检查 (uv-check)

**用途：** 检查 UV 展开质量，发现拉伸、重叠等问题

**特点：**
- 16x16 彩色网格（每格 128 像素）
- 每格显示十六进制坐标（如 3B = 第3行第B列）
- 格子中心有十字准线
- 左下角有 L 形方向标记
- 每种颜色独一无二，便于识别

**输出文件：** `uv_check.png`

### 2. RGB 全身 + 特写 (rgb-closeup)

**用途：** 展示模型原始材质和细节

**特点：**
- 保留模型原始颜色和贴图
- 自动生成全身视图
- 随机选择模型表面一个区域进行特写（约 10% 尺寸）
- 透明背景

**输出文件：** 
- `render_full.png` - 全身图
- `render_closeup.png` - 特写图

### 3. 线框图 (wireframe)

**用途：** 查看模型拓扑结构和边线流向

**特点：**
- 白色模型 + 深灰色线框（1.5 像素宽）
- 全身图和特写图
- 透明背景

**输出文件：**
- `render_full.png` - 全身线框
- `render_closeup.png` - 特写线框

### 4. 白模渲染 (clay)

**用途：** 查看模型形态，不受材质干扰

**特点：**
- 统一的浅灰色材质（粗糙度 0.6）
- 双光源照明（主光 + 补光）
- 透明背景

**输出文件：** `render.png`

### 5. 法线图 (normal-map)

**用途：** 可视化模型表面法线方向，检查曲面朝向和拓扑质量

**特点：**
- 表面法线映射为 RGB 颜色（X→红，Y→绿，Z→蓝）
- 法线从 [-1,1] 重映射到 [0,1] 颜色空间
- 正对相机的平面显示为浅蓝色 (0.5, 0.5, 1.0)
- 支持世界空间（world）和切线空间（tangent）法线
- 透明背景

**输出文件：** `render.png`

**命令行选项：**
```bash
robin normal-map D:\models --normal-space world  # 世界空间（默认）
robin normal-map D:\models --normal-space tangent  # 切线空间
```

## 输出目录结构

使用交互式启动器或"全部渲染"模式时，输出结构如下：

```
模型文件夹/
├── model1.glb
├── model2.glb
└── robin_output/
    ├── uv_check/
    │   ├── model1.png
    │   └── model2.png
    ├── rgb_closeup/
    │   ├── model1_full.png
    │   ├── model1_closeup.png
    │   ├── model2_full.png
    │   └── model2_closeup.png
    ├── wireframe/
    │   ├── model1_full.png
    │   ├── model1_closeup.png
    │   ├── model2_full.png
    │   └── model2_closeup.png
    ├── clay/
    │   ├── model1.png
    │   └── model2.png
    └── normal_map/
        ├── model1.png
        └── model2.png
```

## 常见问题

### 找不到 Blender

**错误信息：** `找不到 Blender!`

**解决方法：**
1. 确认已安装 Blender
2. 检查环境变量 `BLENDER_PATH` 是否设置正确
3. 重启终端或 PowerShell 窗口

### 模型渲染结果是黑色

**可能原因：**
- 模型没有 UV 映射（仅影响 UV 检查模式）
- 模型尺寸过大或过小导致相机距离计算异常

**解决方法：**
- 检查模型是否有 UV 展开
- 尝试其他渲染模式（如白模渲染）

### 渲染速度慢

**优化建议：**
- 降低分辨率（如使用 1280x720）
- 确保 Blender 使用 GPU 加速（在 Blender 首选项中设置）

## 技术细节

### 相机设置

所有渲染模式使用统一的相机算法：
- 自动计算模型包围盒
- 将包围盒 8 个顶点投影到相机局部坐标系
- 计算水平和垂直方向所需距离
- 取最大值并添加 2% 边距
- 相机方向：`(1.0, -1.0, 0.6)` 归一化

### 渲染引擎

- 默认使用 EEVEE（实时渲染引擎）
- 支持 Blender 4.x 和 5.x 版本
- 自动处理 `BLENDER_EEVEE` 和 `BLENDER_EEVEE_NEXT` 的兼容性

### 输出格式

- 格式：PNG
- 颜色模式：RGBA（支持透明通道）
- 背景：透明

## 开发信息

- 项目地址：D:\blender-robin
- Python 版本：3.8+
- 依赖：Click, Blender 3.0+

## 许可证

MIT License
