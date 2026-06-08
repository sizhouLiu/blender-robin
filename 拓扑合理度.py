#!/usr/bin/env python3
"""拓扑合理度评分脚本 - 使用 score_engine 通用引擎"""

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

RPM = 30                # Requests per minute
MAX_RETRIES = 3         # Max retries for failed cases
MAX_CONCURRENT = 10     # Max concurrent requests
GLOBAL_FILE_PATHS = {
    "GLOBAL_FILE_example_topo_good_full_png": "bos://uv-test/robin_renders/wireframe/global/example_topo_good_full.png",
    "GLOBAL_FILE_example_topo_good_close_png": "bos://uv-test/robin_renders/wireframe/global/example_topo_good_close.png",
    "GLOBAL_FILE_example_topo_bad_full_png": "bos://uv-test/robin_renders/wireframe/global/example_topo_bad_full.png",
    "GLOBAL_FILE_example_topo_bad_close_png": "bos://uv-test/robin_renders/wireframe/global/example_topo_bad_close.png"
}
# ============================================================================
# Task configuration (auto-generated from CapArena task)
# ============================================================================

PROMPT_TEMPLATE = [
    {
        "type": "text",
        "content": "你是专业3D拓扑评审专家，对【拓扑合理度】打分，满分100分，仅输出JSON，禁止多余内容。\n\n【输入说明】\n输入包含两张正方形拼接图：\n1. overall.png：2×2 布局，固定为正面、侧面、45°斜视角、背面，用于观察整体布线走向、面数分布与结构完整性；\n2. closeup.png：2×2 布局，为4个随机关键区域特写（覆盖核心部件、接缝、中部结构、细节密集区），用于观察局部面片形态、布线细节与面数密度。\n请结合全局与局部综合评估拓扑合理性。\n\n【任务】基于法线+线框图评估布线流向、面片健康度、面数分布合理性。本标准适用于所有3D模型类别（角色、硬表面机械、场景道具等），判断逻辑与模型类别无关。"
    },
    {
        "type": "text",
        "content": "\n【good 示例】\n- 全身图：布线顺应形体转折，走向整洁；面片规整，无细长/畸形面；面数分布自适应\n- 特写图：左侧为复杂结构区域，布线顺应形体、面片形态健康；右侧为平坦区域，面数分布合理、无过度细分"
    },
    {
        "type": "image",
        "content": "example_topo_good_full.png"
    },
    {
        "type": "image",
        "content": "example_topo_good_close.png"
    },
    {
        "type": "text",
        "content": "\n【bad 示例】\n- 全身图：布线杂乱交叉、无视形体结构；大量细长/星形面；面数分布极端不均（平坦区过密、关键区过稀）\n- 特写图：左侧为复杂结构区域，面片杂乱、大量细长三角面/星形面；右侧为平坦区域，面数过载、过度细分"
    },
    {
        "type": "image",
        "content": "example_topo_bad_full.png"
    },
    {
        "type": "image",
        "content": "example_topo_bad_close.png"
    },
    {
        "type": "text",
        "content": "\n【评分维度】\n1. 布线流向（edge_flow_score，45分）\n- 高分：布线顺应形体转折与轮廓，走向整洁有序\n- 低分：布线杂乱交叉、随意穿破曲面、无视形体主方向\n\n2. 面片质量（face_quality_score，35分）\n- 三角面完全允许，不扣分\n- 低分：出现细长尖锐面、星形面、退化面等形态畸形的面片\n\n3. 分布合理性（density_score，20分）\n- 高分：复杂结构面数较密，平坦区域较疏，分布自适应\n- 低分：全局无脑均匀细分，或关键轮廓面数过稀出现锯齿\n\n【分类规则】\ngood:    80~100  布线顺畅、面片健康、分布合理\nmedium:  40~79   少量瑕疵但整体可用\nbad:      0~39   布线严重混乱、大量畸形面、分布极差\n\n【输出严格按以下格式】\n{\n  \"score\": 0~100,\n  \"edge_flow_score\": 0~45,\n  \"face_quality_score\": 0~35,\n  \"density_score\": 0~20,\n  \"grade\": \"good/medium/bad\",\n  \"issues\": []\n}"
    },
    {
        "type": "input_image",
        "content": "topology_all.png"
    },
    {
        "type": "input_image",
        "content": "topology_closeup_all.png"
    }
]

OUTPUT_SPEC = [
    {
        "name": "score",
        "type": "int",
        "description": "拓扑合理度总分 0-100"
    },
    {
        "name": "edge_flow_score",
        "type": "int",
        "description": "布线流向 0-45"
    },
    {
        "name": "face_quality_score",
        "type": "int",
        "description": "面片质量 0-35"
    },
    {
        "name": "density_score",
        "type": "int",
        "description": "分布合理性 0-20"
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
