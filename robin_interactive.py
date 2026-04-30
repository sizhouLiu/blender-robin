"""
Robin Interactive - 交互式渲染启动器
用法: python robin_interactive.py
"""
import json
import msvcrt
import os
import sys
from pathlib import Path

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
    "views": ["diagonal", "front", "back", "left", "right", "top", "bottom", "diagonal_back"],
    "closeup_count": 1,
    "composite": True,
    "uv_style": "color_grid",
}


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


AFTER_ACTIONS = [
    ("继续渲染", "again"),
    ("打开输出文件夹", "open"),
    ("返回主菜单", "main"),
]

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
    ("全部渲染", "all"),
]


def enable_ansi():
    """Enable ANSI escape codes on Windows."""
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
        key = msvcrt.getwch()
        if key == '\r':  # Enter
            return selected
        if key == '\x1b' or key == '\x00' or key == '\xe0':
            # Arrow key prefix on Windows
            key2 = msvcrt.getwch()
            if key2 == 'H':  # Up
                selected = (selected - 1) % total
                draw()
            elif key2 == 'P':  # Down
                selected = (selected + 1) % total
                draw()


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
    args = [
        "--blender", str(blender_path),
        command,
        str(directory),
        "-o", str(output_dir),
        "-r", str(resolution[0]), str(resolution[1]),
        "--closeup-count", str(closeup_count),
    ]
    if views:
        args += ["--views", ",".join(views)]
    if not composite:
        args.append("--no-composite")
    if command == "uv-check":
        args += ["--style", cfg.get("uv_style", "color_grid")]
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
            (f"渲染视角数: {len(cfg.get('views', all_views))}", "views"),
            (f"特写数量: {cfg.get('closeup_count', 1)}", "closeup"),
            (f"拼合大图: {'是' if cfg.get('composite', True) else '否'}", "composite"),
            (f"UV 风格: {cfg.get('uv_style', 'color_grid')}", "uv_style"),
            ("保存并返回", "save"),
        ]
        idx = select_menu("修改配置 (↑↓ 选择, Enter 修改):", items)
        _, key = items[idx]

        if key == "save":
            save_config(cfg)
            print(f"\n  {GREEN}配置已保存到 {CONFIG_PATH}{RESET}\n")
            return cfg

        if key == "views":
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

        elif key == "composite":
            cur = cfg.get("composite", True)
            cfg["composite"] = not cur
            print(f"\n  {GREEN}已切换为: {'是' if not cur else '否'}{RESET}\n")

        elif key == "uv_style":
            cur = cfg.get("uv_style", "color_grid")
            new = "checker" if cur == "color_grid" else "color_grid"
            cfg["uv_style"] = new
            print(f"\n  {GREEN}已切换为: {new}{RESET}\n")


def do_render(blender, directory, res, cfg):
    """Select render mode and execute."""
    selected = select_menu("选择渲染模式 (↑↓ 选择, Enter 确认):", RENDER_MODES)
    mode_name, mode_cmd = RENDER_MODES[selected]
    print(f"\n  已选择: {GREEN}{mode_name}{RESET}\n")

    base_output = directory / "robin_output"

    if mode_cmd == "all":
        commands = [("uv-check", "uv_check"), ("rgb-closeup", "rgb_closeup"),
                    ("wireframe", "wireframe"), ("clay", "clay")]
    else:
        commands = [(mode_cmd, mode_cmd.replace("-", "_"))]

    print(f"{BOLD}{CYAN}{'─' * 40}{RESET}")
    global_map = {
        "uv-check": "uv-global",
        "rgb-closeup": "rgb-global",
        "wireframe": "wireframe-global",
        "clay": "clay-global",
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

    print(f"\n{BOLD}{CYAN}{'─' * 40}{RESET}")
    print(f"\n  {GREEN}全部完成!{RESET}")
    print(f"  输出目录: {WHITE}{base_output}{RESET}\n")

    while True:
        action_idx = select_menu("下一步:", AFTER_ACTIONS)
        _, action = AFTER_ACTIONS[action_idx]
        if action == "open":
            os.startfile(str(base_output))
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

    # Resolution from config
    default_res = cfg.get("resolution", [1920, 1080])
    sys.stdout.write(f"{CYAN}分辨率 (直接回车使用 {default_res[0]}x{default_res[1]}): {RESET}")
    sys.stdout.flush()
    raw = input().strip()
    if not raw:
        res = (default_res[0], default_res[1])
    else:
        parts = raw.replace("x", " ").replace("X", " ").replace(",", " ").split()
        if len(parts) == 2:
            try:
                res = (int(parts[0]), int(parts[1]))
            except ValueError:
                res = (default_res[0], default_res[1])
                print(f"  {YELLOW}格式不对，使用默认 {default_res[0]}x{default_res[1]}{RESET}")
        else:
            res = (default_res[0], default_res[1])
            print(f"  {YELLOW}格式不对，使用默认 {default_res[0]}x{default_res[1]}{RESET}")
    print(f"  分辨率: {WHITE}{res[0]} x {res[1]}{RESET}\n")

    # Main menu loop
    while True:
        idx = select_menu("主菜单:", MAIN_MENU)
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
