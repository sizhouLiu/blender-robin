#!/usr/bin/env python3
"""细节丰富度评分脚本 - 使用 score_engine 通用引擎"""

import os
import asyncio

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from score_engine import run_scoring

# ============================================================================
# 任务配置 - 只需修改这部分
# ============================================================================

MODEL_NAME = "gemini-3.1-flash-lite-preview-m-high-t-low-temp-0.00"
RPM = 30
MAX_RETRIES = 5
MAX_CONCURRENT = 10

GLOBAL_FILE_PATHS = {
    "GLOBAL_FILE_example_clarity_good_overall_png": "bos://rgb-test/robin_renders/rgb_closeup/global/example_clarity_good_overall.png",
    "GLOBAL_FILE_example_clarity_good_closeup_png": "bos://rgb-test/robin_renders/rgb_closeup/global/example_clarity_good_closeup.png",
    "GLOBAL_FILE_example_clarity_bad_overall_png": "bos://rgb-test/robin_renders/rgb_closeup/global/example_clarity_bad_overall.png",
    "GLOBAL_FILE_example_clarity_bad_closeup_png": "bos://rgb-test/robin_renders/rgb_closeup/global/example_clarity_bad_closeup.png",
}


# ============================================================================
# Task configuration (auto-generated from CapArena task)
# ============================================================================

PROMPT_TEMPLATE = [
    {
        "type": "text",
        "content": "你是专业3D资产质量评审专家，对【纹理清晰度】打分，满分100分，仅输出JSON，禁止多余内容。\n\n【输入说明】\n输入包含两张正方形拼接图：\n1. overall.png：2×2 布局，固定为正面、侧面、45°斜视角、背面，用于观察整体纹理清晰度、低分辨率失真与大范围模糊情况；\n2. closeup.png：2×2 布局，为4个随机关键区域特写（覆盖核心部件、接缝、中部结构、细节密集区），用于观察局部纹理锐利度、锯齿与拉伸糊化。\n请结合全局与局部综合评估纹理清晰度。\n\n【任务】评估纹理是否清晰、锐利，无模糊、锯齿、低分辨率放大感、拉伸糊化。合理的多组件交界不计为清晰度问题。"
    },
    {
        "type": "text",
        "content": "\n【good 示例】\n- overall 图：纹理清晰锐利，边缘干净，文字/标识可辨，无低分辨率失真\n- closeup 图：局部细节锐利，无锯齿、无拉伸糊化，标签/铭牌文字清晰可读"
    },
    {
        "type": "image",
        "content": "example_clarity_good_overall.png"
    },
    {
        "type": "image",
        "content": "example_clarity_good_closeup.png"
    },
    {
        "type": "text",
        "content": "\n【bad 示例】\n- overall 图：纹理整体呈大像素块/马赛克感，低分辨率劣质感明显\n- closeup 图：局部边缘锯齿严重，文字/细节糊化丢失，纹理被强行拉大导致失真"
    },
    {
        "type": "image",
        "content": "example_clarity_bad_overall.png"
    },
    {
        "type": "image",
        "content": "example_clarity_bad_closeup.png"
    },
    {
        "type": "text",
        "content": "\n【评分维度】\n1. 锐利度（sharpness_score，30分）\n- 高分：边缘干净，不软塌、不发虚，文字/细节可辨\n- 低分：边缘模糊、软塌，文字/细节丢失\n\n2. 无低分辨率失真（resolution_score，40分）\n- 高分：无马赛克、无强行拉大的糊感，分辨率充足\n- 低分：明显马赛克/大像素块，糊化，低分辨率劣质感\n\n3. 无锯齿/拉伸（distortion_score，30分）\n- 高分：无明显锯齿、无贴图拉伸导致的形变\n- 低分：锯齿严重、拉伸糊化，局部变形\n\n 如若没有纹理 全黑或者全白直接给出0分\n\n【分类规则】\ngood:    80~100  全程清晰锐利，无失真\nmedium:  40~79   轻微模糊或微小锯齿\nbad:      0~39   明显糊化、严重锯齿、低分辨率劣质\n\n【输出严格按以下格式】\n{\n  \"score\": 0~100,\n  \"sharpness_score\": 0~30,\n  \"resolution_score\": 0~40,\n  \"distortion_score\": 0~30,\n  \"grade\": \"good/medium/bad\",\n  \"issues\": []\n}"
    },
    {
        "type": "input_image",
        "content": "texture_fidelity_all.png"
    },
    {
        "type": "input_image",
        "content": "texture_fidelity_closeup_all.png"
    }
]

OUTPUT_SPEC = [
    {
        "name": "score",
        "type": "int",
        "description": "纹理清晰度总分 0-100"
    },
    {
        "name": "sharpness_score",
        "type": "int",
        "description": "锐利度 0-30"
    },
    {
        "name": "resolution_score",
        "type": "int",
        "description": "无低分辨率失真 0-40"
    },
    {
        "name": "distortion_score",
        "type": "int",
        "description": "无锯齿/拉伸 0-30"
    },
    {
        "name": "grade",
        "type": "string",
        "description": "good/medium/bad"
    },
    {
        "name": "issues",
        "type": "list[str]",
        "description": "扣分原因"
    }
]

# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    asyncio.run(run_scoring(
        bos_endpoint=os.environ.get("BOS_ENDPOINT", "bj.bcebos.com").replace("https://", "").replace("http://", ""),
        bos_access_key=os.environ["BOS_ACCESS_KEY"],
        bos_secret_key=os.environ["BOS_SECRET_KEY"],
        deerapi_base_url=os.environ.get("DEERAPI_BASE_URL", "https://api.deerapi.com"),
        deerapi_key=os.environ["DEERAPI_KEY"],
        model_name=MODEL_NAME,
        rpm=RPM,
        max_retries=MAX_RETRIES,
        max_concurrent=MAX_CONCURRENT,
        global_file_paths=GLOBAL_FILE_PATHS,
        prompt_template=PROMPT_TEMPLATE,
        output_schema=OUTPUT_SPEC,
    ))
