#!/usr/bin/env python3
"""
递归复制指定目录下所有.glb文件到脚本所在目录
"""

import os
import shutil
from pathlib import Path


def copy_glb_files(source_dir: str, dest_dir: str = None):
    """
    递归查找source_dir下所有.glb文件，复制到dest_dir

    Args:
        source_dir: 源目录路径
        dest_dir: 目标目录路径（默认为脚本所在目录）
    """
    # 默认目标目录为脚本所在目录
    if dest_dir is None:
        dest_dir = Path(__file__).parent
    else:
        dest_dir = Path(dest_dir)

    source_path = Path(source_dir)

    if not source_path.exists():
        print(f"错误: 源目录不存在: {source_dir}")
        return

    # 确保目标目录存在
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 递归查找所有.glb文件
    glb_files = list(source_path.rglob("*.glb"))

    if not glb_files:
        print(f"未找到任何.glb文件: {source_dir}")
        return

    print(f"找到 {len(glb_files)} 个.glb文件")

    copied_count = 0
    skipped_count = 0

    for glb_file in glb_files:
        # 获取相对路径，用于处理同名文件
        rel_path = glb_file.relative_to(source_path)

        # 构建目标文件名（保留父目录名避免冲突）
        # 例如: models/character/hero.glb -> character_hero.glb
        if len(rel_path.parts) > 1:
            # 多级目录，用下划线连接父目录名和文件名
            parent_parts = "_".join(rel_path.parts[:-1])
            dest_filename = f"{parent_parts}_{glb_file.name}"
        else:
            dest_filename = glb_file.name

        dest_file = dest_dir / dest_filename

        # 检查目标文件是否已存在
        if dest_file.exists():
            # 如果文件内容相同则跳过，否则添加序号
            if dest_file.stat().st_size == glb_file.stat().st_size:
                print(f"跳过(已存在): {glb_file.name}")
                skipped_count += 1
                continue
            else:
                # 添加序号避免覆盖
                counter = 1
                stem = dest_file.stem
                while dest_file.exists():
                    dest_filename = f"{stem}_{counter}.glb"
                    dest_file = dest_dir / dest_filename
                    counter += 1

        try:
            shutil.copy2(glb_file, dest_file)
            print(f"✓ 复制: {glb_file} -> {dest_file.name}")
            copied_count += 1
        except Exception as e:
            print(f"✗ 失败: {glb_file} - {e}")

    print(f"\n完成! 复制: {copied_count}, 跳过: {skipped_count}")


if __name__ == "__main__":
    import sys

    # 从命令行参数获取源目录，或使用当前目录
    if len(sys.argv) > 1:
        source_directory = sys.argv[1]
    else:
        # 默认使用当前工作目录
        source_directory = input("请输入源目录路径(留空使用当前目录): ").strip()
        if not source_directory:
            source_directory = "."

    # 可选：指定目标目录
    if len(sys.argv) > 2:
        target_directory = sys.argv[2]
    else:
        target_directory = None  # 默认为脚本所在目录

    copy_glb_files(source_directory, target_directory)
