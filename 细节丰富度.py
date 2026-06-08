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

MODEL_NAME = "gemini-3.5-flash"
RPM = 30
MAX_RETRIES = 5
MAX_CONCURRENT = 10

# 全局示例图 BOS 路径
GLOBAL_FILE_PATHS = {
    "GLOBAL_FILE_example_detail_good_overall_png": "bos://rgb-test/robin_renders/rgb_closeup/global/example_detail_good_overall.png",
    "GLOBAL_FILE_example_detail_good_closeup_png": "bos://rgb-test/robin_renders/rgb_closeup/global/example_detail_good_closeup.png",
    "GLOBAL_FILE_example_detail_bad_overall_png": "bos://rgb-test/robin_renders/rgb_closeup/global/example_detail_bad_overall.png",
    "GLOBAL_FILE_example_detail_bad_closeup_png": "bos://rgb-test/robin_renders/rgb_closeup/global/example_detail_bad_closeup.png",
}

PROMPT_TEMPLATE = [
    {
        "type": "text",
        "content": "你是专业3D资产质量评审专家，对【细节丰富度】打分，满分100分，仅输出JSON，禁止多余内容。\n\n【输入说明】\n输入包含两张正方形拼接图：\n1. overall.png：2×2 布局，固定为正面、侧面、45°斜视角、背面，用于观察整体纹理细节与层次表现；\n2. closeup.png：2×2 布局，为4个随机关键区域特写（覆盖核心部件、接缝、中部结构、细节密集区），用于观察局部纹理高频信息与材质区分度。\n请结合全局与局部综合评估细节丰富度。\n\n【任务】\n第一步：先识别模型【风格】与【资产类型】\n- 风格只能四选一：\n  写实：高细节，还原真实物理结构\n  卡通：造型风格化，形体简化\n  极简：极度简化，无多余细节\n  工业：硬表面机械，硬朗结构\n- 资产类型只能三选一：角色、道具、场景\n- **注意：资产类型仅作为元数据标签，不影响后续评分逻辑**\n\n第二步：基于纹理图，在【识别出的风格标准下】评估纹理高频信息量与设计层次。\n不同风格有不同标准：\n- 写实/工业：要求纹理高频信息丰富、材质层次清晰\n- 卡通：允许适度简化，但关键区域纹理特征要鲜明\n- 极简：允许高频信息极少，但整体设计层次要干净利落\n不评价审美，只看纹理细节质量。本标准适用于所有3D模型类别，判断逻辑与模型类别无关。"
    },
    {
        "type": "text",
        "content": "\n【good 示例】\n- overall 图：纹理高频信息充足，材质层次清晰，设计表达完整\n- closeup 图：局部细节鲜明，材质区分度高，关键区域纹理特征突出"
    },
    {"type": "image", "content": "example_detail_good_overall.png"},
    {"type": "image", "content": "example_detail_good_closeup.png"},
    {
        "type": "text",
        "content": "\n【bad 示例】\n- overall 图：纹理高频信息匮乏，大面积素化，材质层次模糊\n- closeup 图：局部细节丢失，材质区分度低，关键区域特征平淡"
    },
    {"type": "image", "content": "example_detail_bad_overall.png"},
    {"type": "image", "content": "example_detail_bad_closeup.png"},
    {
        "type": "text",
        "content": "\n【评分维度】\n1. 细节信息量（info_score，60分）\n- 高分：纹理高频信息充足，有清晰的刻线、磨损、图案等细节（风格自适应）\n- 低分：纹理高频信息匮乏，大面积素化，关键区域细节丢失\n\n2. 层次区分度（layer_score，40分）\n- 高分：不同材质/区域区分清晰，设计层次分明（风格自适应）\n- 低分：材质/区域边界模糊，层次混乱，无明显设计表达\n\n如若没有纹理 全黑或者全白直接给出0分\n\n【分类规则】\ngood:    80~100  纹理细节充足、层次清晰，符合当前风格预期\nmedium:  40~79   少量细节平淡或层次模糊，整体仍符合风格预期\nbad:      0~39   纹理细节严重匮乏、层次混乱，不符合当前风格预期\n\n【输出严格按以下格式】\n{\n  \"score\": 0~100,\n  \"info_score\": 0~60,\n  \"layer_score\": 0~40,\n  \"style\": \"写实/卡通/极简/工业\",\n  \"asset_type\": \"角色/道具/场景\",\n  \"grade\": \"good/medium/bad\",\n  \"issues\": []\n}"
    },
    {"type": "input_image", "content": "texture_fidelity_all.png"},
    {"type": "input_image", "content": "texture_fidelity_closeup_all.png"},
]

OUTPUT_SPEC = [
    {
        "name": "score",
        "type": "int",
        "description": "细节丰富度总分 0-100"
    },
    {
        "name": "info_score",
        "type": "int",
        "description": "细节信息量 0-60"
    },
    {
        "name": "layer_score",
        "type": "int",
        "description": "层次区分度 0-40"
    },
    {
        "name": "style",
        "type": "string",
        "description": "模型风格：写实/卡通/极简/工业"
    },
    {
        "name": "asset_type",
        "type": "string",
        "description": "资产类型：角色/道具/场景"
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
