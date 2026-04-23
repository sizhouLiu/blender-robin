"""
Robin Interactive - 交互式渲染启动器
用法: python robin_interactive.py
"""
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


def input_path(prompt):
    """Get a directory path from user with validation."""
    while True:
        sys.stdout.write(f"{CYAN}{prompt}{RESET}")
        sys.stdout.flush()
        path = input().strip().strip('"').strip("'")
        if not path:
            print(f"  {YELLOW}请输入路径{RESET}")
            continue
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


def input_resolution():
    """Get resolution with default."""
    sys.stdout.write(f"{CYAN}分辨率 (直接回车使用 1920x1080): {RESET}")
    sys.stdout.flush()
    raw = input().strip()
    if not raw:
        return 1920, 1080
    parts = raw.replace("x", " ").replace("X", " ").replace(",", " ").split()
    if len(parts) == 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    print(f"  {YELLOW}格式不对，使用默认 1920x1080{RESET}")
    return 1920, 1080


def run_render(command, directory, output_dir, resolution):
    """Execute a robin render command."""
    from blender_robin.cli import cli
    args = [
        command,
        str(directory),
        "-o", str(output_dir),
        "-r", str(resolution[0]), str(resolution[1]),
    ]
    try:
        cli(args, standalone_mode=False)
    except SystemExit:
        pass
    except Exception as e:
        print(f"  {YELLOW}渲染出错: {e}{RESET}")


def main():
    enable_ansi()

    print(f"\n{BOLD}{CYAN}{'=' * 40}{RESET}")
    print(f"{BOLD}{WHITE}  Robin Render Toolkit{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 40}{RESET}\n")

    # Check Blender
    from blender_robin.discovery import discover_blender, BlenderNotFoundError
    try:
        blender = discover_blender()
        print(f"  Blender: {GREEN}{blender}{RESET}\n")
    except BlenderNotFoundError:
        print(f"  {YELLOW}找不到 Blender!{RESET}")
        print(f"  请设置环境变量: {WHITE}$env:BLENDER_PATH = \"D:\\blender.exe\"{RESET}\n")
        input("按回车退出...")
        return

    # Input directory
    directory = input_path("模型文件夹路径: ")
    print()

    # Select render mode
    selected = select_menu("选择渲染模式 (↑↓ 选择, Enter 确认):", RENDER_MODES)
    mode_name, mode_cmd = RENDER_MODES[selected]
    print(f"\n  已选择: {GREEN}{mode_name}{RESET}\n")

    # Resolution
    res = input_resolution()
    print(f"  分辨率: {WHITE}{res[0]} x {res[1]}{RESET}\n")

    # Output directory
    base_output = directory / "robin_output"
    (base_output / "global").mkdir(parents=True, exist_ok=True)

    if mode_cmd == "all":
        commands = [("uv-check", "uv_check"), ("rgb-closeup", "rgb_closeup"),
                    ("wireframe", "wireframe"), ("clay", "clay")]
    else:
        commands = [(mode_cmd, mode_cmd.replace("-", "_"))]

    # Run
    print(f"{BOLD}{CYAN}{'─' * 40}{RESET}")
    for cmd, folder in commands:
        output_dir = base_output / folder
        label = next((name for name, c in RENDER_MODES if c == cmd), cmd)
        print(f"\n  {WHITE}▶ {label}{RESET}")
        run_render(cmd, directory, output_dir, res)

    print(f"\n{BOLD}{CYAN}{'─' * 40}{RESET}")
    print(f"\n  {GREEN}全部完成!{RESET}")
    print(f"  输出目录: {WHITE}{base_output}{RESET}\n")
    input("按回车退出...")


if __name__ == "__main__":
    main()
