"""
Robin Interactive - 交互式渲染启动器
用法: python robin_interactive.py
"""
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
    "uv_style": "color_grid",
    "output_format": "PNG",
    "hdri_path": "",
    "env_texture": "",
    "export_metadata": False,
    "wireframe_mode": "clay",
    "animation_frame": None,
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
    ("编辑配置", "config"),
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


def select_folder():
    """Open Windows folder picker dialog."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory(title="选择模型文件夹")
    root.destroy()
    return folder


def input_path(prompt):
    """Get a directory path from user with validation."""
    while True:
        sys.stdout.write(f"{CYAN}{prompt}{RESET}{DIM}(直接回车打开文件夹选择器){RESET}\n")
        sys.stdout.flush()
        path = input("  ").strip().strip('"').strip("'")
        if not path:
            path = select_folder()
            if not path:
                print(f"  {YELLOW}未选择文件夹{RESET}")
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
        total = glb_count + gltf_count
        if total == 0:
            print(f"  {YELLOW}该文件夹下没有找到 .glb/.gltf 文件{RESET}")
            continue
        print(f"  {GREEN}找到 {total} 个模型文件{RESET}")
        return p


def run_render(command, directory, output_dir, resolution, blender_path, cfg):
    """Execute a robin render command."""
    from blender_robin.cli import cli
    views = cfg.get("views", [])
    closeup_count = cfg.get("closeup_count", 1)
    composite = cfg.get("composite", True)
    delete_views = cfg.get("delete_views", False)
    parallel = cfg.get("parallel", 1)
    output_format = cfg.get("output_format", "PNG")
    hdri_path = cfg.get("hdri_path", "")
    env_texture = cfg.get("env_texture", "")
    export_metadata = cfg.get("export_metadata", False)
    wireframe_mode = cfg.get("wireframe_mode", "clay")
    animation_frame = cfg.get("animation_frame", None)

    args = [
        "--blender", str(blender_path),
        command,
        str(directory),
        "-o", str(output_dir),
        "-r", str(resolution[0]), str(resolution[1]),
        "--closeup-count", str(closeup_count),
        "-j", str(parallel),
        "--format", output_format,
    ]
    if views:
        args += ["--views", ",".join(views)]
    if not composite:
        args.append("--no-composite")
    if delete_views:
        args.append("--delete-views")
    if hdri_path:
        args += ["--hdri", hdri_path]
    if env_texture:
        args += ["--env-texture", env_texture]
    if export_metadata:
        args.append("--export-metadata")
    if animation_frame is not None:
        args += ["--animation-frame", str(animation_frame)]
    if command == "uv-check":
        args += ["--style", cfg.get("uv_style", "color_grid")]
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
            (f"并行渲染数: {cfg.get('parallel', 1)}", "parallel"),
            (f"UV 风格: {cfg.get('uv_style', 'color_grid')}", "uv_style"),
            (f"线框模式: {cfg.get('wireframe_mode', 'clay')}", "wireframe_mode"),
            (f"输出格式: {cfg.get('output_format', 'PNG')}", "output_format"),
            (f"HDR 环境贴图路径: {cfg.get('hdri_path', '(未设置)')}", "hdri_path"),
            (f"指定环境贴图: {cfg.get('env_texture', '(自动选择)')}", "env_texture"),
            (f"导出元数据 (meta.json): {'是' if cfg.get('export_metadata', False) else '否'}", "export_metadata"),
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


def do_render(blender, directory, res, cfg):
    """Select render mode and execute."""
    selected = select_menu("选择渲染模式 (↑↓ 选择, Enter 确认, Esc 返回):", RENDER_MODES)
    if selected < 0:
        return
    mode_name, mode_cmd = RENDER_MODES[selected]
    if mode_cmd == "back":
        return
    print(f"\n  已选择: {GREEN}{mode_name}{RESET}\n")

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
        run_render(cmd, directory, output_dir, res, blender, cfg)

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

    # Compress each rendered folder into its own zip
    print(f"  {DIM}正在压缩...{RESET}", end="", flush=True)
    zip_files = zip_render_folders(base_output, commands)
    print(f"\r  {GREEN}已生成 {len(zip_files)} 个 zip:                     ")
    for z in zip_files:
        print(f"    {WHITE}{z.name}{RESET}")

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
            if sys.platform == "win32":
                os.startfile(str(base_output))
            elif sys.platform == "darwin":
                import subprocess
                subprocess.run(["open", str(base_output)])
            else:
                import subprocess
                subprocess.run(["xdg-open", str(base_output)])
            print(f"\n  {GREEN}已打开文件夹{RESET}\n")
        elif action == "again":
            print()
            return do_render(blender, directory, res, cfg)
        else:
            return


def main():
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

    # Input directory
    directory = input_path("模型文件夹路径: ")
    print()

    res = tuple(cfg.get("resolution", [1920, 1080]))
    print(f"  分辨率: {WHITE}{res[0]} x {res[1]}{RESET}\n")

    # Main menu loop
    while True:
        idx = select_menu("主菜单 (Esc 退出):", MAIN_MENU)
        if idx < 0:
            return
        _, action = MAIN_MENU[idx]
        if action == "render":
            print()
            do_render(blender, directory, res, cfg)
        elif action == "config":
            cfg = edit_config(cfg)
        else:
            return


if __name__ == "__main__":
    main()
