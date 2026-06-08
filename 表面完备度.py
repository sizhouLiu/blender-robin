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
    "GLOBAL_FILE_example_surface_good_overall_png": "bos://uv-test/robin_renders/normal_map/global/example_surface_good_overall.png",
    "GLOBAL_FILE_example_surface_good_closeup_png": "bos://uv-test/robin_renders/normal_map/global/example_surface_good_closeup.png",
    "GLOBAL_FILE_example_surface_bad_overall_png": "bos://uv-test/robin_renders/normal_map/global/example_surface_bad_overall.png",
    "GLOBAL_FILE_example_surface_bad_closeup_png": "bos://uv-test/robin_renders/normal_map/global/example_surface_bad_closeup.png",
}

PROMPT_TEMPLATE = [
    {
        "type": "text",
        "content": "你是专业3D资产质量评审专家，对【表面完备度】打分，满分100分，仅输出JSON，禁止多余内容。\n\n【输入说明】\n输入包含两张正方形拼接图：\n1. overall.png：2×2 布局，固定为正面、侧面、45°斜视角、背面，用于观察整体表面完整性、穿模与大面积破面情况；\n2. closeup.png：2×2 布局，为4个随机关键区域特写（覆盖核心部件、接缝、中部结构、细节密集区），用于观察局部孔洞、裂缝、微小破面与不合理穿插。\n请结合全局与局部综合评估表面完备度。\n\n【任务】基于灰模图评估模型表面与结构完整性，判断是否存在明显不合理穿模、破面、孔洞等几何缺陷。合理的相嵌/嵌套结构不计为穿模。"
    },
    {
        "type": "text",
        "content": "\n【good 示例】\n- overall 图：表面完整封闭，无不合理穿插，边界清晰自然\n- closeup 图：表面光滑闭合，无破洞、无裂缝，结构干净整洁"
    },
    {
        "type": "image",
        "content": "example_surface_good_overall.png"
    },
    {
        "type": "image",
        "content": "example_surface_good_closeup.png"
    },
    {
        "type": "text",
        "content": "\n【bad 示例】\n- overall 图：存在明显不合理穿模、表面破面孔洞等缺陷\n- closeup 图：可见无理由穿透、表面明显漏空破洞，几何完整性被破坏"
    },
    {
        "type": "image",
        "content": "example_surface_bad_overall.png"
    },
    {
        "type": "image",
        "content": "example_surface_bad_closeup.png"
    },
    {
        "type": "text",
        "content": "\n【评分维度】\n1. 无穿模（interpenetration_score，50分）\n- 高分：无不合理穿插，合理相嵌/嵌套结构边界清晰\n- 低分：存在明显无理由穿模、几何干涉\n\n2. 无破面孔洞（cracks_holes_score，50分）\n- 高分：表面封闭完整，无可见孔洞、裂缝、漏空\n- 低分：出现明显破洞、裂缝、异常发黑的镂空\n\n【分类规则】\ngood:    80~100  表面完整，无明显缺陷\nmedium:  40~79   轻微小瑕疵，不影响整体使用\nbad:      0~39   明显穿模、破面、孔洞，几何不完整\n\n【输出严格按以下格式】\n{\n  \"score\": 0~100,\n  \"interpenetration_score\": 0~50,\n  \"cracks_holes_score\": 0~50,\n  \"grade\": \"good/medium/bad\",\n  \"issues\": []\n}"
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
        "description": "表面完备度总分 0-100"
    },
    {
        "name": "interpenetration_score",
        "type": "int",
        "description": "无穿模 0-50"
    },
    {
        "name": "cracks_holes_score",
        "type": "int",
        "description": "无破面孔洞 0-50"
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
