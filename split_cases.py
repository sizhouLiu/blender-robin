#!/usr/bin/env python
"""将 表面完备度.json 拆解为 expected-output/case_XXX.json 文件。"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(BASE_DIR, "材质还原度.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "expected-output")
KEY_NAME = "gemini-3.1-pro-preview-m-high-t-low"


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    cases = data.get("cases", [])
    if not cases:
        print("错误: 未找到 cases 字段")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    count = 0
    for case in cases:
        case_id = case.get("case_id", f"case_{count+1:03d}")
        model_outputs = case.get("model_outputs", {})

        if KEY_NAME not in model_outputs:
            print(f"  跳过 {case_id}: 缺少 '{KEY_NAME}' 的输出")
            continue

        output_path = os.path.join(OUTPUT_DIR, f"{case_id}.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(model_outputs[KEY_NAME], f, ensure_ascii=False, indent=2)

        print(f"  ✓ {case_id}.json")
        count += 1

    print(f"\n完成: 共生成 {count} 个文件 -> {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
