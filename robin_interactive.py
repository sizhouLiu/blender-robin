"""
Robin Interactive - 交互式渲染启动器
用法: python robin_interactive.py
"""
import argparse
import json
import os
import sys
from pathlib import Path

# ---------- 跨平台按键读取 ----------
if sys.platform == "win32":
    import msvcrt

    def _read_key():
        key = msvcrt.getwch()
        if key in ('\r', '\n'):
            return 'enter'
        if key in ('\x00', '\xe0'):
            key2 = msvcrt.getwch()
            if key2 == 'H':
                return 'up'
            if key2 == 'P':
                return 'down'
            return None
        if key == '\x1b':
            return 'esc'
        return None

else:
    import tty
    import termios
    import select as _select

    def _read_key():
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = os.read(fd, 1).decode('utf-8', errors='replace')
            if ch in ('\r', '\n'):
                return 'enter'
            if ch == '\x1b':
                if _select.select([sys.stdin], [], [], 0.05)[0]:
                    ch2 = os.read(fd, 1).decode('utf-8', errors='replace')
                    if ch2 == '[' and _select.select([sys.stdin], [], [], 0.05)[0]:
                        ch3 = os.read(fd, 1).decode('utf-8', errors='replace')
                        if ch3 == 'A':
                            return 'up'
                        if ch3 == 'B':
                            return 'down'
                return 'esc'
            return None
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

# ANSI colors
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
WHITE = "\033[97m"
DIM = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"
CLEAR_LINE = "\033[2K"
UP = "\033[A"

CONFIG_PATH = Path(__file__).parent / "robin_config.json"

DEFAULT_CONFIG = {
    "blender_path": "",
    "resolution": [1920, 1080],
    "parallel": 2,
    "views": ["diagonal", "front", "back", "left", "right", "top", "bottom", "diagonal_back"],
    "closeup_count": 1,
    "composite": True,
    "delete_views": False,
    "delete_closeups": False,
    "uv_style": "color_grid",
    "output_format": "PNG",
    "hdri_path": "",
    "env_texture": "",
    "export_metadata": False,
    "wireframe_mode": "clay",
    "animation_frame": None,
    "camera_json": "",
    "enable_log": True,
    "export_blender_uv": False,
    "bos_env_path": "",
    "bos_manifest": "",
    "bos_output_dir": "",
    "bos_limit": None,
    "bos_batch_size": 10,
    "bos_delete_after_render": False,
    "bos_upload_bucket": "",
    "bos_upload_prefix": "robin_renders",
    "bos_upload_after_render": False,
    "bos_delete_local_after_upload": False,
    "pfs_output_dir": "/mnt/pfs/users/sizhou",
    "zip_output": True,

}


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


MAIN_MENU = [
    ("渲染图片", "render"),
    ("上传渲染结果到 BOS", "upload_bos"),
    ("从 BOS 拉取并渲染", "bos"),
    ("编辑配置", "config"),
    ("重新选择文件夹", "change_dir"),
    ("退出", "exit"),
]

RENDER_MODES = [
    ("UV 棋盘格检查", "uv-check"),
    ("RGB 全身 + 特写", "rgb-closeup"),
    ("线框图 (全身 + 特写)", "wireframe"),
    ("白模渲染", "clay"),
    ("法线图", "normal-map"),
    ("反照率图 (Albedo)", "albedo"),
    ("全部渲染", "all"),
    ("← 返回主菜单", "back"),
]


def enable_ansi():
    """Enable ANSI escape codes on Windows (no-op on other platforms)."""
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)


def select_menu(title, options):
    """Interactive menu with arrow key selection. Returns index."""
    selected = 0
    total = len(options)

    def draw():
        # Move cursor up to redraw
        for _ in range(total):
            sys.stdout.write(UP + CLEAR_LINE)
        for i, (label, _) in enumerate(options):
            if i == selected:
                sys.stdout.write(f"  {GREEN}> {label}{RESET}\n")
            else:
                sys.stdout.write(f"    {DIM}{label}{RESET}\n")
        sys.stdout.flush()

    # Initial draw
    sys.stdout.write(f"\n{CYAN}{title}{RESET}\n\n")
    for i, (label, _) in enumerate(options):
        if i == selected:
            sys.stdout.write(f"  {GREEN}> {label}{RESET}\n")
        else:
            sys.stdout.write(f"    {DIM}{label}{RESET}\n")
    sys.stdout.flush()

    while True:
        key = _read_key()
        if key == 'enter':
            return selected
        if key == 'up':
            selected = (selected - 1) % total
            draw()
        elif key == 'down':
            selected = (selected + 1) % total
            draw()
        elif key == 'esc':
            return -1


def _has_gui():
    """Whether a GUI file dialog / file manager can run on this platform."""
    if sys.platform in ("win32", "darwin"):
        return True
    # Linux/other: a display server must be present (X11 or Wayland)
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _open_folder(path):
    """Open a folder in the OS file manager. Returns False if not possible."""
    path = str(path)
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", path])
        else:
            if not _has_gui():
                return False
            import subprocess
            result = subprocess.run(
                ["xdg-open", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                return False
        return True
    except Exception:
        return False


def select_folder():
    """Open a GUI folder picker dialog. Returns '' if no GUI is available."""
    if not _has_gui():
        return ""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return ""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory(title="选择模型文件夹")
    root.destroy()
    return folder


def input_path(prompt):
    """Get a directory path from user with validation."""
    gui = _has_gui()
    while True:
        hint = f"{DIM}(直接回车打开文件夹选择器){RESET}" if gui else ""
        sys.stdout.write(f"{CYAN}{prompt}{RESET}{hint}\n")
        sys.stdout.flush()
        path = input("  ").strip().strip('"').strip("'")
        if not path:
            path = select_folder()
            if not path:
                if gui:
                    print(f"  {YELLOW}未选择文件夹{RESET}")
                else:
                    print(f"  {YELLOW}请输入文件夹路径{RESET}")
                continue
            print(f"  {WHITE}{path}{RESET}")
        p = Path(path)
        if not p.exists():
            print(f"  {YELLOW}路径不存在: {path}{RESET}")
            continue
        if not p.is_dir():
            print(f"  {YELLOW}不是文件夹: {path}{RESET}")
            continue
        glb_count = len(list(p.glob("*.glb")))
        gltf_count = len(list(p.glob("*.gltf")))
        blend_count = len(list(p.glob("*.blend")))
        total = glb_count + gltf_count + blend_count
        if total == 0:
            print(f"  {YELLOW}该文件夹下没有找到 .glb/.gltf/.blend 文件{RESET}")
            continue
        print(f"  {GREEN}找到 {total} 个模型文件 (glb:{glb_count} gltf:{gltf_count} blend:{blend_count}){RESET}")
        return p


def run_render(command, directory, output_dir, resolution, blender_path, cfg, recursive=False):
    """Execute a robin render command."""
    from blender_robin.cli import cli
    views = cfg.get("views", [])
    closeup_count = cfg.get("closeup_count", 1)
    composite = cfg.get("composite", True)
    delete_views = cfg.get("delete_views", False)
    delete_closeups = cfg.get("delete_closeups", False)
    parallel = cfg.get("parallel", 1)
    output_format = cfg.get("output_format", "PNG")
    hdri_path = cfg.get("hdri_path", "")
    env_texture = cfg.get("env_texture", "")
    export_metadata = cfg.get("export_metadata", False)
    wireframe_mode = cfg.get("wireframe_mode", "clay")
    animation_frame = cfg.get("animation_frame", None)
    camera_json = cfg.get("camera_json", "")

    # Always pass all supported model types; CLI handles comma-separated patterns.
    # recursive=True 时使用 ** 递归匹配 (用于 BOS 下载的 {source}/{uuid}/{file} 嵌套结构)
    if recursive:
        pattern = "**/*.glb,**/*.gltf,**/*.blend"
        glb_count = len(list(directory.rglob("*.glb"))) + len(list(directory.rglob("*.gltf")))
        blend_count = len(list(directory.rglob("*.blend")))
    else:
        pattern = "*.glb,*.gltf,*.blend"
        glb_count = len(list(directory.glob("*.glb"))) + len(list(directory.glob("*.gltf")))
        blend_count = len(list(directory.glob("*.blend")))
    print(f"  {DIM}检测到: {glb_count} 个 GLB/GLTF, {blend_count} 个 BLEND → 使用模式: {pattern}{RESET}")

    args = [
        "--blender", str(blender_path),
        command,
        str(directory),
        "-o", str(output_dir),
        "-r", str(resolution[0]), str(resolution[1]),
        "--closeup-count", str(closeup_count),
        "-j", str(parallel),
        "--format", output_format,
        "--pattern", pattern,
    ]
    if views:
        args += ["--views", ",".join(views)]
    if not composite:
        args.append("--no-composite")
    if delete_views:
        args.append("--delete-views")
    if delete_closeups:
        args.append("--delete-closeups")
    if hdri_path:
        args += ["--hdri", hdri_path]
    if env_texture:
        args += ["--env-texture", env_texture]
    if export_metadata:
        args.append("--export-metadata")
    if animation_frame is not None:
        args += ["--animation-frame", str(animation_frame)]
    if camera_json:
        args += ["--camera-json", camera_json]
    if command == "uv-check":
        args += ["--style", cfg.get("uv_style", "color_grid")]
        if not cfg.get("enable_seam_overlay", True):
            args.append("--no-seam-overlay")
        if not cfg.get("export_uv_layout", True):
            args.append("--no-uv-layout")
        if cfg.get("export_blender_uv", False):
            args.append("--blender-uv")
    if not cfg.get("enable_log", True):
        args.append("--no-log")
    if command == "wireframe":
        args += ["--mode", wireframe_mode]
    try:
        cli(args, standalone_mode=False)
    except SystemExit:
        pass
    except Exception as e:
        print(f"  {YELLOW}渲染出错: {e}{RESET}")


def edit_config(cfg):
    """Interactive config editor."""
    all_views = ["diagonal", "front", "back", "left", "right", "top", "bottom", "diagonal_back"]
    while True:
        items = [
            (f"分辨率: {cfg.get('resolution', [1920,1080])[0]}x{cfg.get('resolution', [1920,1080])[1]}", "resolution"),
            (f"渲染视角数: {len(cfg.get('views', all_views))}", "views"),
            (f"特写数量: {cfg.get('closeup_count', 1)}", "closeup"),
            (f"动画帧: {cfg.get('animation_frame', '(默认第1帧)')}", "animation_frame"),
            (f"拼合大图: {'是' if cfg.get('composite', True) else '否'}", "composite"),
            (f"删除非特写图: {'是' if cfg.get('delete_views', False) else '否'}", "delete_views"),
            (f"删除特写图: {'是' if cfg.get('delete_closeups', False) else '否'}", "delete_closeups"),
            (f"并行渲染数: {cfg.get('parallel', 1)}", "parallel"),
            (f"UV 风格: {cfg.get('uv_style', 'color_grid')}", "uv_style"),
            (f"接缝叠加: {'是' if cfg.get('enable_seam_overlay', True) else '否'}", "enable_seam_overlay"),
            (f"导出 UV Layout: {'是' if cfg.get('export_uv_layout', True) else '否'}", "export_uv_layout"),
            (f"导出 Blender UV Layout (前台): {RED + '是 ⚠ 前台运行' + RESET if cfg.get('export_blender_uv', False) else '否'}", "export_blender_uv"),
            (f"线框模式: {cfg.get('wireframe_mode', 'clay')}", "wireframe_mode"),
            (f"输出格式: {cfg.get('output_format', 'PNG')}", "output_format"),
            (f"渲染完成后压缩: {'是' if cfg.get('zip_output', True) else '否'}", "zip_output"),
            (f"HDR 环境贴图路径: {cfg.get('hdri_path', '(未设置)')}", "hdri_path"),
            (f"指定环境贴图: {cfg.get('env_texture', '(自动选择)')}", "env_texture"),
            (f"导出元数据 (meta.json): {'是' if cfg.get('export_metadata', False) else '否'}", "export_metadata"),
            (f"相机参考文件: {cfg.get('camera_json', '(不指定)') or '(不指定)'}", "camera_json"),
            (f"写入日志文件: {'是' if cfg.get('enable_log', True) else '否'}", "enable_log"),
            (f"BOS 上传 bucket: {cfg.get('bos_upload_bucket', '(未设置)') or '(未设置)'}", "bos_upload_bucket"),
            (f"BOS 上传前缀: {cfg.get('bos_upload_prefix', 'robin_renders')}", "bos_upload_prefix"),
            (f"渲染后自动上传 BOS: {'是' if cfg.get('bos_upload_after_render', False) else '否'}", "bos_upload_after_render"),
            (f"上传后删除本地文件: {'是' if cfg.get('bos_delete_local_after_upload', False) else '否'}", "bos_delete_local_after_upload"),
            (f"PFS 输出目录: {cfg.get('pfs_output_dir', '/mnt/pfs/users/sizhou')}", "pfs_output_dir"),
            ("保存并返回", "save"),
            ("← 返回 (不保存)", "back"),
        ]
        idx = select_menu("修改配置 (↑↓ 选择, Enter 修改, Esc 返回):", items)
        _, key = items[idx] if idx >= 0 else ("", "back")

        if key == "back":
            return cfg

        if key == "save":
            save_config(cfg)
            print(f"\n  {GREEN}配置已保存到 {CONFIG_PATH}{RESET}\n")
            return cfg

        if key == "resolution":
            cur = cfg.get("resolution", [1920, 1080])
            sys.stdout.write(f"\n  {CYAN}分辨率 (当前 {cur[0]}x{cur[1]}, 格式如 1920x1080): {RESET}")
            sys.stdout.flush()
            raw = input().strip()
            if raw:
                parts = raw.replace("x", " ").replace("X", " ").replace(",", " ").split()
                if len(parts) == 2:
                    try:
                        cfg["resolution"] = [int(parts[0]), int(parts[1])]
                        print(f"  {GREEN}已更新{RESET}\n")
                    except ValueError:
                        print(f"  {YELLOW}格式不对{RESET}\n")

        elif key == "views":
            current = cfg.get("views", all_views)
            print(f"\n  {CYAN}当前视角: {', '.join(current)}{RESET}")
            print(f"  {DIM}可选: {', '.join(all_views)}{RESET}")
            sys.stdout.write(f"  {CYAN}输入视角 (逗号分隔, 回车保持不变): {RESET}")
            sys.stdout.flush()
            raw = input().strip()
            if raw:
                cfg["views"] = [v.strip() for v in raw.split(",") if v.strip() in all_views]
                print(f"  {GREEN}已更新{RESET}\n")

        elif key == "closeup":
            sys.stdout.write(f"\n  {CYAN}特写数量 (当前 {cfg.get('closeup_count', 1)}): {RESET}")
            sys.stdout.flush()
            raw = input().strip()
            if raw.isdigit():
                cfg["closeup_count"] = int(raw)
                print(f"  {GREEN}已更新{RESET}\n")

        elif key == "animation_frame":
            cur = cfg.get("animation_frame", None)
            cur_str = str(cur) if cur is not None else "(默认第1帧)"
            sys.stdout.write(f"\n  {CYAN}动画帧 (当前 {cur_str}, 输入帧号如 30, 留空恢复默认): {RESET}")
            sys.stdout.flush()
            raw = input().strip()
            if raw == "":
                cfg["animation_frame"] = None
                print(f"  {GREEN}已恢复默认 (第1帧){RESET}\n")
            elif raw.isdigit() and int(raw) >= 1:
                cfg["animation_frame"] = int(raw)
                print(f"  {GREEN}已更新为第 {raw} 帧{RESET}\n")
            else:
                print(f"  {YELLOW}请输入正整数{RESET}\n")

        elif key == "composite":
            cur = cfg.get("composite", True)
            cfg["composite"] = not cur
            print(f"\n  {GREEN}已切换为: {'是' if not cur else '否'}{RESET}\n")

        elif key == "delete_views":
            cur = cfg.get("delete_views", False)
            cfg["delete_views"] = not cur
            print(f"\n  {GREEN}已切换为: {'是' if not cur else '否'}{RESET}\n")

        elif key == "delete_closeups":
            cur = cfg.get("delete_closeups", False)
            cfg["delete_closeups"] = not cur
            print(f"\n  {GREEN}已切换为: {'是' if not cur else '否'}{RESET}\n")

        elif key == "parallel":
            sys.stdout.write(f"\n  {CYAN}并行渲染数 (当前 {cfg.get('parallel', 1)}, 建议不超过 CPU 核心数): {RESET}")
            sys.stdout.flush()
            raw = input().strip()
            if raw.isdigit() and int(raw) >= 1:
                cfg["parallel"] = int(raw)
                print(f"  {GREEN}已更新{RESET}\n")

        elif key == "uv_style":
            cur = cfg.get("uv_style", "color_grid")
            new = "checker" if cur == "color_grid" else "color_grid"
            cfg["uv_style"] = new
            print(f"\n  {GREEN}已切换为: {new}{RESET}\n")

        elif key == "enable_seam_overlay":
            cfg["enable_seam_overlay"] = not cfg.get("enable_seam_overlay", True)
            print(f"\n  {GREEN}接缝叠加: {'已开启' if cfg['enable_seam_overlay'] else '已关闭'}{RESET}\n")

        elif key == "export_uv_layout":
            cfg["export_uv_layout"] = not cfg.get("export_uv_layout", True)
            print(f"\n  {GREEN}导出 UV Layout: {'已开启' if cfg['export_uv_layout'] else '已关闭'}{RESET}\n")

        elif key == "export_blender_uv":
            cfg["export_blender_uv"] = not cfg.get("export_blender_uv", False)
            state = cfg["export_blender_uv"]
            note = " (将以前台模式运行 Blender)" if state else ""
            print(f"\n  {GREEN}导出 Blender UV Layout: {'已开启' if state else '已关闭'}{note}{RESET}\n")

        elif key == "wireframe_mode":
            modes = ["clay", "normal", "face_normal", "material"]
            descs = {
                "clay":        "灰模 MatCap + 线框 (basic_1.exr)",
                "normal":      "法线 MatCap + 线框 (check_normal+y.exr)",
                "face_normal": "面法线彩色 + 线框 (EEVEE)",
                "material":    "白模 + 着色器线框 (EEVEE)",
            }
            cur = cfg.get("wireframe_mode", "clay")
            new = modes[(modes.index(cur) + 1) % len(modes)] if cur in modes else "clay"
            cfg["wireframe_mode"] = new
            print(f"\n  {GREEN}已切换为: {new} ({descs[new]}){RESET}\n")

        elif key == "output_format":
            formats = ["PNG", "JPEG", "WEBP", "EXR", "TIFF", "BMP"]
            cur = cfg.get("output_format", "PNG")
            cur_idx = formats.index(cur) if cur in formats else 0
            new_idx = (cur_idx + 1) % len(formats)
            cfg["output_format"] = formats[new_idx]
            print(f"\n  {GREEN}已切换为: {formats[new_idx]}{RESET}\n")

        elif key == "hdri_path":
            sys.stdout.write(f"\n  {CYAN}HDR 环境贴图文件夹路径 (当前: {cfg.get('hdri_path', '(未设置)')}): {RESET}")
            sys.stdout.flush()
            raw = input().strip().strip('"').strip("'")
            if raw:
                cfg["hdri_path"] = raw
                print(f"  {GREEN}已更新{RESET}\n")
            elif raw == "" and cfg.get("hdri_path"):
                cfg["hdri_path"] = ""
                print(f"  {GREEN}已清除{RESET}\n")

        elif key == "env_texture":
            sys.stdout.write(f"\n  {CYAN}指定环境贴图文件名 (当前: {cfg.get('env_texture', '(自动选择)')}, 留空自动选择): {RESET}")
            sys.stdout.flush()
            raw = input().strip()
            cfg["env_texture"] = raw
            print(f"  {GREEN}已更新{RESET}\n")

        elif key == "export_metadata":
            cur = cfg.get("export_metadata", False)
            cfg["export_metadata"] = not cur
            print(f"\n  {GREEN}已切换为: {'是' if not cur else '否'}{RESET}\n")

        elif key == "camera_json":
            cur = cfg.get("camera_json", "")
            sys.stdout.write(f"\n  {CYAN}相机参考文件路径 (当前: {cur or '(不指定)'}, 留空清除): {RESET}")
            sys.stdout.flush()
            raw = input().strip().strip('"').strip("'")
            if raw:
                cfg["camera_json"] = raw
                print(f"  {GREEN}已设置为: {raw}{RESET}\n")
            else:
                cfg["camera_json"] = ""
                print(f"  {GREEN}已清除{RESET}\n")

        elif key == "enable_log":
            cfg["enable_log"] = not cfg.get("enable_log", True)
            print(f"\n  {GREEN}写入日志文件: {'已开启' if cfg['enable_log'] else '已关闭'}{RESET}\n")

        elif key == "zip_output":
            cfg["zip_output"] = not cfg.get("zip_output", True)
            print(f"\n  {GREEN}渲染完成后压缩: {'已开启' if cfg['zip_output'] else '已关闭'}{RESET}\n")

        elif key == "bos_upload_bucket":
            cur = cfg.get("bos_upload_bucket", "")
            sys.stdout.write(f"\n  {CYAN}BOS 上传 bucket (当前: {cur or '(未设置)'}, 留空清除): {RESET}")
            sys.stdout.flush()
            raw = input().strip()
            cfg["bos_upload_bucket"] = raw
            print(f"  {GREEN}已更新{RESET}\n")

        elif key == "bos_upload_prefix":
            cur = cfg.get("bos_upload_prefix", "robin_renders")
            sys.stdout.write(f"\n  {CYAN}BOS 上传路径前缀 (当前: {cur}): {RESET}")
            sys.stdout.flush()
            raw = input().strip()
            if raw:
                cfg["bos_upload_prefix"] = raw
                print(f"  {GREEN}已更新{RESET}\n")

        elif key == "bos_upload_after_render":
            cfg["bos_upload_after_render"] = not cfg.get("bos_upload_after_render", False)
            state = cfg["bos_upload_after_render"]
            print(f"\n  {GREEN}渲染后自动上传 BOS: {'已开启' if state else '已关闭'}{RESET}\n")

        elif key == "bos_delete_local_after_upload":
            cfg["bos_delete_local_after_upload"] = not cfg.get("bos_delete_local_after_upload", False)
            state = cfg["bos_delete_local_after_upload"]
            print(f"\n  {GREEN}上传后删除本地文件: {'已开启' if state else '已关闭'}{RESET}\n")

        elif key == "pfs_output_dir":
            cur = cfg.get("pfs_output_dir", "/mnt/pfs/users/sizhou")
            sys.stdout.write(f"\n  {CYAN}PFS 输出目录 (当前: {cur}): {RESET}")
            sys.stdout.flush()
            raw = input().strip().strip('"').strip("'")
            if raw:
                cfg["pfs_output_dir"] = raw
                print(f"  {GREEN}已更新{RESET}\n")


def clear_render_folders(base_output, commands):
    """Remove only the subfolders that are about to be re-rendered."""
    import shutil
    deleted = 0
    for _, folder in commands:
        target = base_output / folder
        if target.exists():
            shutil.rmtree(target)
            deleted += 1
    # Also clear the checkerboard copy when rgb-closeup is included
    if any(cmd == "rgb-closeup" for cmd, _ in commands):
        cb = base_output / "checkerboard"
        if cb.exists():
            shutil.rmtree(cb)
            deleted += 1
    if deleted:
        print(f"  {YELLOW}已清空 {deleted} 个旧输出文件夹{RESET}")


def zip_render_folders(base_output, commands):
    """Compress each rendered subfolder into its own zip file."""
    import shutil
    zip_files = []
    for _, folder in commands:
        target = base_output / folder
        if target.exists():
            zip_base = str(base_output / folder)
            result = shutil.make_archive(zip_base, "zip", root_dir=str(base_output), base_dir=folder)
            zip_files.append(Path(result))
    # Also zip checkerboard if rgb-closeup was rendered
    if any(cmd == "rgb-closeup" for cmd, _ in commands):
        cb = base_output / "checkerboard"
        if cb.exists():
            zip_base = str(base_output / "checkerboard")
            result = shutil.make_archive(zip_base, "zip", root_dir=str(base_output), base_dir="checkerboard")
            zip_files.append(Path(result))
    return zip_files


def do_render(blender, directory, res, cfg, recursive=False, mode_cmd=None):
    """Select render mode and execute."""
    if mode_cmd is None:
        selected = select_menu("选择渲染模式 (↑↓ 选择, Enter 确认, Esc 返回):", RENDER_MODES)
        if selected < 0:
            return
        mode_name, mode_cmd = RENDER_MODES[selected]
        if mode_cmd == "back":
            return
        print(f"\n  已选择: {GREEN}{mode_name}{RESET}\n")
    else:
        mode_name = next((n for n, c in RENDER_MODES if c == mode_cmd), mode_cmd)

    base_output = directory / "robin_output"

    if mode_cmd == "all":
        commands = [("uv-check", "uv_check"), ("rgb-closeup", "rgb_closeup"),
                    ("wireframe", "wireframe"), ("clay", "clay"), ("normal-map", "normal_map"),
                    ("albedo", "albedo")]
    else:
        commands = [(mode_cmd, mode_cmd.replace("-", "_"))]

    # Clear only the subfolders being re-rendered, leave others untouched
    clear_render_folders(base_output, commands)

    print(f"{BOLD}{CYAN}{'─' * 40}{RESET}")
    global_map = {
        "uv-check": "uv-global",
        "rgb-closeup": "rgb-global",
        "wireframe": "wireframe-global",
        "clay": "clay-global",
        "normal-map": "normal-map-global",
        "albedo": "albedo-global",
    }
    for cmd, folder in commands:
        output_dir = base_output / folder
        label = next((name for name, c in RENDER_MODES if c == cmd), cmd)
        print(f"\n  {WHITE}▶ {label}{RESET}")
        run_render(cmd, directory, output_dir, res, blender, cfg, recursive=recursive)

        src_global = directory / global_map[cmd]
        dst_global = output_dir / "global"
        dst_global.mkdir(parents=True, exist_ok=True)
        if src_global.is_dir():
            import shutil
            count = 0
            for f in src_global.iterdir():
                if f.is_file():
                    shutil.copy2(f, dst_global / f.name)
                    count += 1
            if count:
                print(f"  {GREEN}复制 {count} 个文件到 global/{RESET}")

        # RGB 渲染完成后，复制整个 RGB 文件夹为 checkerboard，global 用 checkerboard-global
        if cmd == "rgb-closeup":
            import shutil
            checkerboard_dir = base_output / "checkerboard"
            if checkerboard_dir.exists():
                shutil.rmtree(checkerboard_dir)
            shutil.copytree(output_dir, checkerboard_dir)
            print(f"  {GREEN}已复制 rgb_closeup/ -> checkerboard/{RESET}")

            # 替换 checkerboard/global 为 checkerboard-global 的内容
            cb_global_dst = checkerboard_dir / "global"
            cb_global_src = directory / "checkerboard-global"
            if cb_global_src.is_dir():
                if cb_global_dst.exists():
                    shutil.rmtree(cb_global_dst)
                cb_global_dst.mkdir(parents=True, exist_ok=True)
                count = 0
                for f in cb_global_src.iterdir():
                    if f.is_file():
                        shutil.copy2(f, cb_global_dst / f.name)
                        count += 1
                if count:
                    print(f"  {GREEN}复制 {count} 个文件到 checkerboard/global/{RESET}")

    print(f"\n{BOLD}{CYAN}{'─' * 40}{RESET}")
    print(f"\n  {GREEN}全部完成!{RESET}")
    print(f"  输出目录: {WHITE}{base_output}{RESET}\n")

    # Upload to BOS (if enabled)
    upload_bucket = cfg.get("bos_upload_bucket", "").strip()
    if cfg.get("bos_upload_after_render", False) and upload_bucket:
        upload_prefix = cfg.get("bos_upload_prefix", "robin_renders").strip().rstrip("/")
        env_path = cfg.get("bos_env_path", "") or str(Path(__file__).parent / ".env")
        delete_local = cfg.get("bos_delete_local_after_upload", False)
        print(f"  {DIM}正在上传到 BOS...{RESET}")
        for _, folder in commands:
            target = base_output / folder
            if target.exists():
                upload_output_to_bos(
                    output_dir=target,
                    model_dir=directory,
                    bucket=upload_bucket,
                    prefix=f"{upload_prefix}/{folder}",
                    env_path=env_path,
                    delete_local=delete_local,
                    recursive=recursive,
                )

    # Compress each rendered folder into its own zip (if enabled)
    if cfg.get("zip_output", True):
        print(f"  {DIM}正在压缩...{RESET}", end="", flush=True)
        zip_files = zip_render_folders(base_output, commands)
        print(f"\r  {GREEN}已生成 {len(zip_files)} 个 zip:                     ")
        for z in zip_files:
            print(f"    {WHITE}{z.name}{RESET}")
    else:
        print(f"  {DIM}(已跳过压缩){RESET}")

    after_actions = [
        ("继续渲染", "again"),
        ("打开输出文件夹", "open"),
        ("返回主菜单", "main"),
    ]

    while True:
        action_idx = select_menu("下一步 (Esc 返回主菜单):", after_actions)
        if action_idx < 0:
            return
        _, action = after_actions[action_idx]
        if action == "open":
            if _open_folder(base_output):
                print(f"\n  {GREEN}已打开文件夹{RESET}\n")
            else:
                print(f"\n  {YELLOW}无法打开文件管理器，输出目录:{RESET}")
                print(f"  {WHITE}{base_output}{RESET}\n")
        elif action == "again":
            print()
            return do_render(blender, directory, res, cfg, recursive=recursive)
        else:
            return


def _input_file(prompt, default="", suffixes=None):
    """Get an existing file path from user. Empty input keeps default if valid."""
    while True:
        hint = f"{DIM}(当前: {default}){RESET}" if default else ""
        sys.stdout.write(f"{CYAN}{prompt}{RESET}{hint}\n")
        sys.stdout.flush()
        raw = input("  ").strip().strip('"').strip("'")
        if not raw and default:
            raw = default
        if not raw:
            print(f"  {YELLOW}请输入路径{RESET}")
            continue
        p = Path(raw)
        if not p.is_file():
            print(f"  {YELLOW}文件不存在: {raw}{RESET}")
            continue
        if suffixes and p.suffix.lower() not in suffixes:
            print(f"  {YELLOW}需要 {'/'.join(suffixes)} 文件{RESET}")
            continue
        return p


def _copy_render_results_to_pfs(batch_dir: Path, pfs_output_dir: str):
    """Copy render results from batch_dir/robin_output to {pfs_output_dir}/{uuid}/.

    Mapping: case_001 → 1st model uuid, case_002 → 2nd model uuid, etc.
    Model files are at batch_dir/{uuid}/{filename}.
    """
    import shutil

    robin_output = batch_dir / "robin_output"
    if not robin_output.exists():
        print(f"  {DIM}无 robin_output 目录，跳过复制到 PFS{RESET}")
        return

    # Collect uuid subdirs sorted by name (same order as rendering enumeration)
    uuid_dirs = sorted([d for d in batch_dir.iterdir()
                        if d.is_dir() and d.name not in ("robin_output",)])

    if not uuid_dirs:
        print(f"  {DIM}批次目录无模型子目录，跳过复制到 PFS{RESET}")
        return

    # Build case_XXX -> uuid mapping
    case_to_uuid = {f"case_{i:03d}": d.name for i, d in enumerate(uuid_dirs, 1)}

    pfs_base = Path(pfs_output_dir)
    copied_cases = 0
    skipped_cases = 0

    for case_id, uuid in case_to_uuid.items():
        # Collect all files under robin_output that belong to this case_id
        case_files = list(robin_output.rglob(f"*/{case_id}/*"))
        case_files += list(robin_output.rglob(f"*/{case_id}"))
        # More reliable: find all paths containing /case_id/
        all_files = [f for f in robin_output.rglob("*") if f.is_file()
                     and (f"/{case_id}/" in f.as_posix().replace("\\", "/")
                          or f.parts[-2] == case_id)]

        if not all_files:
            skipped_cases += 1
            continue

        dst_base = pfs_base / uuid
        for f in all_files:
            # Keep the path relative to robin_output, but replace case_XXX with nothing
            # Final structure: {pfs_output_dir}/{uuid}/{render_type}/{filename}
            rel = f.relative_to(robin_output)
            # rel looks like: uv_check/input/case_001/filename.png
            # Strip the "input/case_XXX" part, keep render_type/filename
            parts = rel.parts
            # Find and remove the case_id segment and its parent "input" segment
            try:
                case_idx = parts.index(case_id)
                # Keep: parts before "input" + parts after case_id
                kept = parts[:case_idx - 1] + parts[case_idx + 1:]
            except ValueError:
                kept = parts

            dst = dst_base / Path(*kept) if kept else dst_base / f.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)

        copied_cases += 1

    print(f"  {GREEN}PFS 复制完成: {copied_cases} 个 case → {pfs_output_dir}/"
          f"{'{uuid}'}  (跳过 {skipped_cases} 个){RESET}")


def _upload_render_results(batch_dir: Path, bucket: str, prefix: str, env_path: str):
    """Upload robin_output from batch_dir to BOS using bce-python-sdk."""
    from blender_robin import bos_fetch
    bos_fetch.load_bos_env(env_path)

    try:
        from baidubce.services.bos.bos_client import BosClient
        from baidubce.auth.bce_credentials import BceCredentials
        from baidubce.bce_client_configuration import BceClientConfiguration
        import os

        client = BosClient(BceClientConfiguration(
            credentials=BceCredentials(
                access_key_id=os.environ["BOS_ACCESS_KEY"],
                secret_access_key=os.environ["BOS_SECRET_KEY"],
            ),
            endpoint=os.environ["BOS_ENDPOINT"],
        ))
    except Exception as e:
        print(f"  {YELLOW}BOS 客户端初始化失败: {e}{RESET}")
        return

    robin_output = batch_dir / "robin_output"
    if not robin_output.exists():
        print(f"  {DIM}无 robin_output 目录，跳过上传{RESET}")
        return

    uploaded = 0
    failed = 0
    for f in robin_output.rglob("*"):
        if not f.is_file():
            continue
        relative = f.relative_to(batch_dir)
        key = f"{prefix}/{relative.as_posix()}"
        try:
            client.put_object_from_file(bucket, key, str(f))
            uploaded += 1
        except Exception as e:
            print(f"  {YELLOW}上传失败 {f.name}: {e}{RESET}")
            failed += 1

    status = f"{GREEN}已上传 {uploaded} 个文件" if not failed else f"{YELLOW}上传 {uploaded} 成功, {failed} 失败"
    print(f"  {status} → {bucket}/{prefix}{RESET}")


def upload_output_to_bos(output_dir: Path, model_dir: Path, bucket: str, prefix: str,
                         env_path: str, delete_local: bool = False, recursive: bool = False):
    """上传渲染结果目录到 BOS。

    遍历 output_dir/input/case_XXX/ 下所有文件，以模型文件 stem 为标识上传。
    路径格式：{prefix}/input/{model_id}/{filename}  (per-case files)
              {prefix}/global/{filename}           (global files)
    返回 (uploaded, failed) 计数。
    """
    from blender_robin import bos_fetch
    bos_fetch.load_bos_env(env_path)

    try:
        from baidubce.services.bos.bos_client import BosClient
        from baidubce.auth.bce_credentials import BceCredentials
        from baidubce.bce_client_configuration import BceClientConfiguration
        import os as _os

        client = BosClient(BceClientConfiguration(
            credentials=BceCredentials(
                access_key_id=_os.environ["BOS_ACCESS_KEY"],
                secret_access_key=_os.environ["BOS_SECRET_KEY"],
            ),
            endpoint=_os.environ["BOS_ENDPOINT"],
        ))
    except Exception as e:
        print(f"  {YELLOW}BOS 客户端初始化失败: {e}{RESET}")
        return 0, 0

    input_dir = output_dir / "input"
    if not input_dir.exists():
        print(f"  {DIM}无 input 目录: {input_dir}{RESET}")
        return 0, 0

    exts = ("*.glb", "*.gltf", "*.obj", "*.fbx", "*.blend", "*.dae",
            "*.usd", "*.usda", "*.usdc", "*.usdz", "*.ply", "*.stl")
    if recursive:
        model_files = []
        for ext in exts:
            model_files.extend(model_dir.rglob(ext))
        model_files = sorted(set(model_files))
    else:
        model_files = []
        for ext in exts:
            model_files.extend(model_dir.glob(ext))
        model_files = sorted(set(model_files))

    model_id_map = {f"case_{i:03d}": f.stem for i, f in enumerate(model_files, 1)}

    case_dirs = sorted([d for d in input_dir.iterdir() if d.is_dir() and d.name.startswith("case_")])

    uploaded = 0
    failed = 0
    for case_dir in case_dirs:
        model_id = model_id_map.get(case_dir.name, case_dir.name)
        for f in case_dir.rglob("*"):
            if not f.is_file():
                continue
            filename = f.relative_to(case_dir).as_posix()
            key = f"{prefix}/input/{model_id}/{filename}"
            try:
                client.put_object_from_file(bucket, key, str(f))
                uploaded += 1
            except Exception as e:
                print(f"  {YELLOW}上传失败 {key}: {e}{RESET}")
                failed += 1

    # 上传 global 目录（如果有）
    global_dir = output_dir / "global"
    if global_dir.exists():
        for f in global_dir.rglob("*"):
            if not f.is_file():
                continue
            filename = f.relative_to(global_dir).as_posix()
            key = f"{prefix}/global/{filename}"
            try:
                client.put_object_from_file(bucket, key, str(f))
                uploaded += 1
            except Exception as e:
                print(f"  {YELLOW}上传失败 {key}: {e}{RESET}")
                failed += 1

    if delete_local and failed == 0:
        import shutil
        shutil.rmtree(output_dir, ignore_errors=True)
        print(f"  {DIM}已删除本地目录: {output_dir}{RESET}")

    status_color = GREEN if not failed else YELLOW
    print(f"  {status_color}BOS 上传完成: {uploaded} 成功, {failed} 失败 → {bucket}/{prefix}{RESET}")
    return uploaded, failed


def do_upload_bos(directory: Path, cfg):
    """手动选择渲染结果文件夹上传到 BOS。"""
    base_output = directory / "robin_output"
    if not base_output.exists():
        print(f"\n  {YELLOW}未找到 robin_output 目录: {base_output}{RESET}\n")
        return

    sub_dirs = sorted([d for d in base_output.iterdir() if d.is_dir()])
    if not sub_dirs:
        print(f"\n  {YELLOW}robin_output 下无子目录{RESET}\n")
        return

    options = [(d.name, d) for d in sub_dirs] + [("← 返回", None)]
    idx = select_menu("选择要上传的渲染结果 (↑↓ 选择, Enter 确认):", options)
    if idx < 0 or options[idx][1] is None:
        return

    selected_dir = options[idx][1]
    print(f"\n  已选择: {GREEN}{selected_dir.name}{RESET}")

    bucket = cfg.get("bos_upload_bucket", "").strip()
    prefix = cfg.get("bos_upload_prefix", "robin_renders").strip().rstrip("/")
    env_path = cfg.get("bos_env_path", "") or str(Path(__file__).parent / ".env")

    if not bucket:
        sys.stdout.write(f"\n  {CYAN}BOS Bucket (未配置，请输入): {RESET}")
        sys.stdout.flush()
        bucket = input().strip()
        if not bucket:
            print(f"  {YELLOW}未输入 bucket，取消上传{RESET}\n")
            return
        cfg["bos_upload_bucket"] = bucket

    print(f"  上传目标: {WHITE}{bucket}/{prefix}/{{model_id}}/...{RESET}")
    sys.stdout.write(f"  {CYAN}确认上传? (Y/n): {RESET}")
    sys.stdout.flush()
    confirm = input().strip().lower()
    if confirm in ("n", "no"):
        print(f"  {DIM}已取消{RESET}\n")
        return

    delete_local = cfg.get("bos_delete_local_after_upload", False)
    upload_output_to_bos(
        output_dir=selected_dir,
        model_dir=directory,
        bucket=bucket,
        prefix=f"{prefix}/{selected_dir.name}",
        env_path=env_path,
        delete_local=delete_local,
    )
    print()


def do_bos_fetch(blender, res, cfg):
    """从 BOS 按 manifest 下载模型, 然后递归渲染。"""
    try:
        from blender_robin import bos_fetch
    except ImportError as e:
        print(f"\n  {RED}无法加载 bos_fetch 模块: {e}{RESET}\n")
        return

    print(f"\n{BOLD}{CYAN}{'─' * 40}{RESET}")
    print(f"  {WHITE}从 BOS 拉取并渲染{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 40}{RESET}\n")

    # 1. .env 路径 (含 BOS 凭证)
    default_env = cfg.get("bos_env_path", "") or str(Path(__file__).parent / ".env")
    env_path = _input_file("BOS .env 路径: ", default=default_env)
    parsed = bos_fetch.load_bos_env(env_path)
    if not all(parsed.get(k) for k in ("BOS_ENDPOINT", "BOS_ACCESS_KEY", "BOS_SECRET_KEY")):
        print(f"\n  {RED}.env 缺少 BOS_ENDPOINT / BOS_ACCESS_KEY / BOS_SECRET_KEY{RESET}\n")
        return
    cfg["bos_env_path"] = str(env_path)
    print(f"  {GREEN}已加载 BOS 凭证: {parsed['BOS_ENDPOINT']}{RESET}\n")

    # 2. manifest JSONL 路径
    manifest = _input_file(
        "manifest 文件路径 (JSONL, 每行含 uuid/old_bucket/old_oss_path/source): ",
        default=cfg.get("bos_manifest", ""),
        suffixes={".jsonl", ".json", ".txt"},
    )
    cfg["bos_manifest"] = str(manifest)

    # 3. 下载输出目录
    default_out = cfg.get("bos_output_dir", "") or str(manifest.parent / "bos_models")
    sys.stdout.write(f"\n{CYAN}下载输出目录 {DIM}(回车用默认: {default_out}){RESET}\n")
    sys.stdout.flush()
    raw_out = input("  ").strip().strip('"').strip("'")
    output_dir = Path(raw_out) if raw_out else Path(default_out)
    cfg["bos_output_dir"] = str(output_dir)

    # 4. limit
    sys.stdout.write(f"\n{CYAN}下载条数上限 {DIM}(回车=全部){RESET}\n")
    sys.stdout.flush()
    raw_limit = input("  ").strip()
    limit = int(raw_limit) if raw_limit.isdigit() and int(raw_limit) > 0 else None
    cfg["bos_limit"] = limit

    # 5. 渲染模式
    render_modes_display = [(n, c) for n, c in RENDER_MODES if c != "back"]
    selected = select_menu("选择渲染模式:", render_modes_display)
    if selected < 0:
        return
    render_mode_name, render_mode_cmd = render_modes_display[selected]
    print(f"\n  已选择: {GREEN}{render_mode_name}{RESET}\n")
    default_delete = cfg.get("bos_delete_after_render", False)
    default_hint = "Y/n" if default_delete else "y/N"
    sys.stdout.write(f"\n{CYAN}渲染后删除模型文件? {DIM}({default_hint}, 回车=保持默认){RESET}\n")
    sys.stdout.flush()
    raw_delete = input("  ").strip().lower()
    if raw_delete in ("y", "yes"):
        delete_after_render = True
    elif raw_delete in ("n", "no"):
        delete_after_render = False
    else:
        delete_after_render = default_delete
    cfg["bos_delete_after_render"] = delete_after_render
    save_config(cfg)

    # 6. 全量下载
    mapping_file = output_dir / "downloaded_model_mapping.jsonl"
    print(f"\n  {WHITE}开始下载 → {output_dir}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 40}{RESET}")
    try:
        stats = bos_fetch.download_manifest(
            manifest=manifest,
            output_base=output_dir,
            limit=limit,
            mapping_file=mapping_file,
            log=lambda msg: print(f"  {DIM}{msg}{RESET}"),
        )
    except Exception as e:
        print(f"\n  {RED}下载失败: {e}{RESET}\n")
        return

    print(f"{BOLD}{CYAN}{'─' * 40}{RESET}")
    print(f"  {GREEN}下载完成: 成功={stats['success']} 跳过={stats['skipped']} "
          f"失败={stats['failed']} (共处理 {stats['processed']}){RESET}")
    print(f"  mapping: {WHITE}{mapping_file}{RESET}\n")

    if stats["success"] == 0:
        print(f"  {YELLOW}没有成功下载的模型, 跳过渲染{RESET}\n")
        return

    # 7. 递归渲染
    upload_bucket = cfg.get("bos_upload_bucket", "").strip()
    upload_prefix = cfg.get("bos_upload_prefix", "robin_renders").strip().rstrip("/")
    pfs_output_dir = cfg.get("pfs_output_dir", "").strip()

    print(f"  {WHITE}进入渲染流程 (递归扫描 {output_dir}){RESET}")
    do_render(blender, output_dir, res, cfg, recursive=True, mode_cmd=render_mode_cmd)

    if upload_bucket:
        _upload_render_results(
            batch_dir=output_dir,
            bucket=upload_bucket,
            prefix=upload_prefix,
            env_path=str(env_path),
        )

    if pfs_output_dir:
        _copy_render_results_to_pfs(output_dir, pfs_output_dir)

    if delete_after_render:
        import shutil
        # 只删模型文件，保留渲染输出
        for d in output_dir.iterdir():
            if d.is_dir() and d.name not in ("robin_output",):
                shutil.rmtree(d, ignore_errors=True)
        print(f"  {DIM}已删除模型文件{RESET}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Robin 交互式渲染启动器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["local", "bos"],
        default=None,
        help="启动模式: local=本地渲染 (需要模型文件夹), bos=从 BOS 拉取并渲染 (不需要本地文件夹)",
    )
    args = parser.parse_args()

    enable_ansi()

    print(f"\n{BOLD}{CYAN}{'=' * 40}{RESET}")
    print(f"{BOLD}{WHITE}  Robin Render Toolkit{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 40}{RESET}\n")

    cfg = load_config()
    print(f"  配置: {GREEN}{CONFIG_PATH}{RESET}\n")

    # Check Blender: config > env var > auto-discovery > ask user
    from blender_robin.discovery import discover_blender, BlenderNotFoundError, get_blender_version
    blender = None
    cfg_blender = cfg.get("blender_path", "")
    if cfg_blender:
        p = Path(cfg_blender)
        if p.is_file():
            blender = p
        else:
            print(f"  {YELLOW}配置中的 blender_path 无效: {cfg_blender}{RESET}")

    if not blender:
        try:
            blender = discover_blender()
        except BlenderNotFoundError:
            pass

    if not blender:
        print(f"  {YELLOW}未找到 Blender，请手动指定路径{RESET}\n")
        while True:
            sys.stdout.write(f"  {CYAN}Blender 路径 (如 D:\\Blender\\blender.exe): {RESET}")
            sys.stdout.flush()
            raw_path = input().strip().strip('"').strip("'")
            if not raw_path:
                print(f"  {YELLOW}请输入路径{RESET}")
                continue
            p = Path(raw_path)
            if not p.is_file():
                print(f"  {YELLOW}文件不存在: {raw_path}{RESET}")
                continue
            try:
                ver = get_blender_version(p)
                print(f"  {GREEN}检测到 Blender {ver}{RESET}")
                blender = p
                cfg["blender_path"] = str(p)
                save_config(cfg)
                print(f"  {GREEN}已保存到配置文件{RESET}\n")
                break
            except Exception:
                print(f"  {YELLOW}无法运行该文件，请确认是 blender.exe{RESET}")
                continue

    print(f"  Blender: {GREEN}{blender}{RESET}\n")

    res = tuple(cfg.get("resolution", [1920, 1080]))
    print(f"  分辨率: {WHITE}{res[0]} x {res[1]}{RESET}\n")

    # Mode-based flow: if --mode is provided, skip menu and run directly
    if args.mode == "bos":
        do_bos_fetch(blender, res, cfg)
        return
    elif args.mode == "local":
        directory = input_path("模型文件夹路径: ")
        print()
        do_render(blender, directory, res, cfg)
        return

    # Interactive menu mode (no --mode flag)
    directory = input_path("模型文件夹路径: ")
    print()

    # Main menu loop
    while True:
        print(f"  文件夹: {WHITE}{directory}{RESET}\n")
        idx = select_menu("主菜单 (Esc 退出):", MAIN_MENU)
        if idx < 0:
            return
        _, action = MAIN_MENU[idx]
        if action == "render":
            print()
            do_render(blender, directory, res, cfg)
        elif action == "upload_bos":
            do_upload_bos(directory, cfg)
        elif action == "bos":
            do_bos_fetch(blender, res, cfg)
        elif action == "config":
            cfg = edit_config(cfg)
            res = tuple(cfg.get("resolution", [1920, 1080]))
        elif action == "change_dir":
            directory = input_path("模型文件夹路径: ")
            print()
        else:
            return


if __name__ == "__main__":
    main()
