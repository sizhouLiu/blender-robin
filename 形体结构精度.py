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


# 全局示例图 BOS 路径
GLOBAL_FILE_PATHS = {
    "GLOBAL_FILE_example_shape_good_overall_png": "bos://uv-test/robin_renders/normal_map/global/example_shape_good_overall.png",
    "GLOBAL_FILE_example_shape_good_closeup_png": "bos://uv-test/robin_renders/normal_map/global/example_shape_good_closeup.png",
    "GLOBAL_FILE_example_shape_bad_overall_png": "bos://uv-test/robin_renders/normal_map/global/example_shape_bad_overall.png",
    "GLOBAL_FILE_example_shape_bad_closeup_png": "bos://uv-test/robin_renders/normal_map/global/example_shape_bad_closeup.png",
}

PROMPT_TEMPLATE = [
    {
        "type": "text",
        "content": "你是专业3D资产质量评审专家，对【形态结构精度】打分，满分100分，仅输出JSON，禁止多余内容。\n\n【输入说明】\n输入包含两张正方形拼接图：\n1. overall.png：2×2 布局，固定为正面、侧面、45°斜视角、背面，用于观察整体形体轮廓、结构完整性与体块关系；\n2. closeup.png：2×2 布局，为4个随机关键区域特写（覆盖核心部件、接缝、中部结构、细节密集区），用于观察局部细节层次、边缘硬度与结构清晰度。\n请结合全局与局部综合评估形态结构精度。\n\n【任务】\n第一步：先识别模型【风格】与【资产类型】\n- 风格只能四选一：\n  写实：高细节，还原真实物理结构\n  卡通：造型风格化，形体简化\n  极简：极度简化，无多余细节\n  工业：硬表面机械，硬朗结构\n- 资产类型只能三选一：角色、道具、场景\n- **注意：资产类型仅作为元数据标签，不影响后续评分逻辑**\n\n第二步：基于灰模图，在【识别出的风格标准下】评估几何结构：细节是否完整、形体轮廓是否清晰、硬边转折是否分明。\n不同风格有不同标准：\n- 写实/工业：要求细节丰富、结构层次多\n- 卡通：允许适度简化，但轮廓必须清晰\n- 极简：允许细节极少，但形体必须干净挺拔\n不评价审美，只看结构质量。本标准适用于所有3D模型类别，判断逻辑与模型类别无关。"
    },
    {
        "type": "text",
        "content": "\n【good 示例】\n- overall 图：细节充足，二三级结构清晰；形体挺拔，硬边转折干脆\n- closeup 图：局部细节有厚度与层次，边缘分明，关键结构完整"
    },
    {
        "type": "image",
        "content": "example_shape_good_overall.png"
    },
    {
        "type": "image",
        "content": "example_shape_good_closeup.png"
    },
    {
        "type": "text",
        "content": "\n【bad 示例】\n- overall 图：表面素化、大面积平淡，无明显二三级结构；形体软塌，特征模糊\n- closeup 图：关键结构缺失，边缘圆塌、分界不清，表面光滑无细节"
    },
    {
        "type": "image",
        "content": "example_shape_bad_overall.png"
    },
    {
        "type": "image",
        "content": "example_shape_bad_closeup.png"
    },
    {
        "type": "text",
        "content": "\n【评分维度】\n1. 细节丰富度（detail_score，50分）\n- 高分：有清晰的二三级结构（如缝隙、扣件、褶皱、凸起、刻线等），细节有厚度与层次（风格自适应）\n- 低分：表面素化、大面积平淡、关键结构缺失\n\n2. 特征清晰度（sharpness_score，50分）\n- 高分：硬边转折干脆、体块分界明确、轮廓挺拔，无软塌模糊（风格自适应）\n- 低分：边缘圆塌、形体软塌、特征分界不清\n\n【分类规则】\ngood:    80~100  细节充足、结构清晰、形体挺拔（符合当前风格预期）\nmedium:  40~79   少量平淡或轻微模糊，整体仍符合风格预期\nbad:      0~39   大面积素化、结构严重模糊、形体软塌（不符合当前风格预期）\n\n【输出严格按以下格式】\n{\n  \"score\": 0~100,\n  \"detail_score\": 0~50,\n  \"sharpness_score\": 0~50,\n  \"style\": \"写实/卡通/极简/工业\",\n  \"asset_type\": \"角色/道具/场景\",\n  \"grade\": \"good/medium/bad\",\n  \"issues\": []\n}"
    },
    {
        "type": "input_image",
        "content": "normal_map_all.png"
    },
    {
        "type": "input_image",
        "content": "normal_map_closeup_all.png"
    }
]

OUTPUT_SPEC = [
    {
        "name": "score",
        "type": "int",
        "description": "形态结构精度总分 0-100"
    },
    {
        "name": "detail_score",
        "type": "int",
        "description": "细节丰富度 0-50"
    },
    {
        "name": "sharpness_score",
        "type": "int",
        "description": "特征清晰度 0-50"
    },
    {
        "name": "style",
        "type": "string",
        "description": "模型风格：写实/卡通/极简/工业"
    },
    {
        "name": "asset_type",
        "type": "string",
        "description": "资产类型：角色/道具/场景，仅作为元数据，不参与评分"
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
