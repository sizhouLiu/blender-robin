# 相机摆放说明 (Camera Placement)

## 实现位置

`blender_robin/blender_scripts/render_views.py` → `setup_camera()`

---

## 透视相机（Diagonal 视角）

### 目标

将相机放置在斜前方，使模型的包围盒恰好填满画面（留 2% 边距）。

### 方向向量

```python
direction = Vector((1.0, -1.0, 0.6)).normalized()
```

相机从这个方向看向模型中心，即右前上方的斜角视角。

### 计算相机距离

核心问题：相机距离多远，包围盒的 8 个角点才能全部在视野内？

**第一步：建立相机坐标系**

```python
cam_forward = -direction                              # 相机朝向（指向模型）
cam_right   = cam_forward.cross(world_up).normalized()  # 相机右方向
cam_up      = cam_right.cross(cam_forward).normalized() # 相机上方向
```

以相机视线方向为基准，构建正交坐标系。

**第二步：枚举包围盒 8 个角点**

```python
corners = [
    Vector((sx * hx, sy * hy, sz * hz))
    for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)
]
```

以包围盒中心为原点，列出所有 8 个角点（相对坐标）。

**第三步：计算角点在相机坐标系中的投影范围**

```python
max_right = max(abs(c.dot(cam_right)) for c in corners)  # 水平方向最大半宽
max_up    = max(abs(c.dot(cam_up))    for c in corners)  # 垂直方向最大半高
```

将每个角点投影到相机的水平轴和垂直轴，取最大值。

**第四步：根据 FOV 反推最小距离**

```python
dist_h = max_right / tan(fov / 2)          # 水平方向需要的距离
vfov   = 2 * atan(tan(fov/2) / aspect)     # 根据宽高比计算垂直 FOV
dist_v = max_up / tan(vfov / 2)            # 垂直方向需要的距离

distance = max(dist_h, dist_v) * 1.02      # 取较大值，留 2% 边距
```

水平和垂直方向各自计算所需距离，取较大值确保两个方向都不裁切。

**第五步：放置相机**

```python
camera.location = center + direction * distance
look_dir = center - camera.location
rot_quat = look_dir.to_track_quat('-Z', 'Y')  # 相机 -Z 轴对准模型，Y 轴朝上
camera.rotation_euler = rot_quat.to_euler()
```

### 示意图

```
        ↑ Z
        |
        |    相机
        |   /
        |  / direction (1, -1, 0.6)
        | /
        |/____________→ X
       /
      / Y（朝屏幕外）
```

---

## 正交相机（Front / Back / Left / Right / Top / Bottom）

正交视角不需要计算 FOV，直接用包围盒最大边长设置正交缩放：

```python
cam_data.type = 'ORTHO'
cam_data.ortho_scale = max_dim * 1.05   # 最大边长 + 5% 边距
direction, rotation = ortho_views[view_name]
camera.location = center + direction * distance  # distance = max_dim * 2
camera.rotation_euler = rotation
```

各视角的方向和旋转：

| 视角 | 方向向量 | 旋转 (Euler) |
|------|----------|--------------|
| front | (0, -1, 0) | (90°, 0°, 0°) |
| back | (0, 1, 0) | (90°, 0°, 180°) |
| left | (-1, 0, 0) | (90°, 0°, -90°) |
| right | (1, 0, 0) | (90°, 0°, 90°) |
| top | (0, 0, 1) | (0°, 0°, 0°) |
| bottom | (0, 0, -1) | (180°, 0°, 0°) |

---

## 球面四视角（`fixed_4view`）

在以模型为中心的球面上，均匀分布 4 个相机位置：

```python
phi   = radians(90 - elevation_deg)   # 仰角 10° → phi = 80°
for angle in [45, 135, 225, 315]:     # 方位角每隔 90°
    theta = radians(angle)
    x = center.x + r * sin(phi) * cos(theta)
    y = center.y + r * sin(phi) * sin(theta)
    z = center.z + r * cos(phi)
```

球坐标系转笛卡尔坐标，`r = max_dim * 1.5`。

---

## 特写相机（Closeup）

特写相机以随机顶点为焦点，计算能包住局部区域的最小距离：

```python
radius     = sub_bbox_size.length / 2.0   # 局部包围球半径
half_angle = min(fov/2, vfov/2)           # 取水平/垂直 FOV 中较小的
distance   = radius / sin(half_angle) * 1.15  # 球体恰好在视野内 + 15% 边距
```

使用球体包围（而非 AABB）是因为特写区域较小，球体近似足够精确，计算更简单。

方向与全身视角相同：`(1.0, -1.0, 0.6).normalized()`。

---

## 动画帧与包围盒的关系

相机距离由包围盒决定，包围盒在 `render_multi_view()` 开始时计算：

```python
scene.frame_set(animation_frame)   # 先切换到目标帧
bpy.context.view_layer.update()
center, bbox_size = get_bounding_box_evaluated(bpy, mesh_objects)  # 再计算包围盒
```

这确保相机是基于**实际渲染帧的姿态**来定位的，而不是 rest pose。对于手臂张开、腿部伸展等动作帧，包围盒会更大，相机会自动拉远以容纳整个姿态。

---

## Clip 范围

```python
cam_data.clip_start = 0.01
cam_data.clip_end   = max(100000, distance * 3)
```

`clip_end` 取 `distance * 3` 和 100000 中的较大值，确保超大模型（归一化前）也不会被裁切。
