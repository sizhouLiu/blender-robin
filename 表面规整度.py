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



BOS_ENDPOINT = os.environ.get("BOS_ENDPOINT", "bj.bcebos.com").replace("https://", "").replace("http://", "")
BOS_ACCESS_KEY = os.environ["BOS_ACCESS_KEY"]
BOS_SECRET_KEY = os.environ["BOS_SECRET_KEY"]
DEERAPI_BASE_URL = os.environ.get("DEERAPI_BASE_URL", "https://api.deerapi.com")
DEERAPI_KEY = os.environ["DEERAPI_KEY"]

MODEL_NAME = "gemini-3.1-pro-preview-m-high-t-low"

RPM = 30                # Requests per minute
MAX_RETRIES = 3         # Max retries for failed cases
MAX_CONCURRENT = 10     # Max concurrent requests

# ============================================================================
# Global file paths
# ============================================================================
GLOBAL_FILE_example_uv_good_full_png = "bos://uv-test/robin_renders/uv_check/global/example_uv_good_full.png"
GLOBAL_FILE_example_uv_good_close_png = "bos://uv-test/robin_renders/uv_check/global/example_uv_good_close.png"
GLOBAL_FILE_example_uv_good_layout_png = "bos://uv-test/robin_renders/uv_check/global/example_uv_good_layout.png"
GLOBAL_FILE_example_uv_bad_full_png = "bos://uv-test/robin_renders/uv_check/global/example_uv_bad_full.png"
GLOBAL_FILE_example_uv_bad_close_png = "bos://uv-test/robin_renders/uv_check/global/example_uv_bad_close.png"
GLOBAL_FILE_example_uv_bad_layout_png = "bos://uv-test/robin_renders/uv_check/global/example_uv_bad_layout.png"
# ============================================================================
# Task configuration (auto-generated from CapArena task)
# ============================================================================

PROMPT_TEMPLATE = [
    {
        "type": "text",
        "content": "你是专业3D资产质量评审专家，对【表面规整度】打分，满分100分，仅输出JSON，禁止多余内容。\n\n【输入说明】\n输入包含两张正方形拼接图：\n1. overall.png：2×2 布局，固定为正面、侧面、45°斜视角、背面，用于观察整体UV拉伸、扭曲、密度分布与接缝布局；\n2. closeup.png：2×2 布局，为4个随机关键区域特写（覆盖核心部件、接缝、中部结构、细节密集区），用于观察局部UV变形、拉伸程度与格子规整性。接缝区域被渲染成了红色。3.layout.png 按一个 UV 空间组导出单张 UV Layout拼接成一张大图查看 UV 排布、岛利用率、接缝位置、重叠 / 翻转 \n请结合全局与局部综合评估UV表面规整度。\n\n【任务】根据棋盘格图评估UV展开质量，判断是否存在扭曲、拉伸、疏密不均、接缝突兀等问题。合理的多组件交界不计为UV缺陷，重点区域可适当提高密度。"
    },
    {
        "type": "text",
        "content": "\n【good 示例】\n- overall 图：棋盘格方块接近正方形，密度均匀，重点区域可适当提高密度，无明显拉伸、扭曲，UV规整\n- closeup 图：局部格子大小一致，无挤压变形，接缝位于不显眼的组件交界\n layout图 高空间利用率 清晰合理的区域划分 方向一致性极佳"
    },
    {
        "type": "image",
        "content": "example_uv_good_full.png"
    },
    {
        "type": "image",
        "content": "example_uv_good_close.png"
    },
    {
        "type": "image",
        "content": "example_uv_good_layout.png"
    },
    {
        "type": "text",
        "content": "\n【bad 示例】\n- overall 图：棋盘格明显拉伸、挤压变形、扭曲歪斜、疏密不均，重点区域密度异常稀疏或过度拉伸\n- closeup 图：局部UV呈歪斜/细长条变形，格子被严重拉伸或压扁，重点区域细节丢失\n layout图 灾难性的 UV 岛重叠与交叉 极度混乱的边缘畸变与锯齿化 毫无方向性可言"
    },
    {
        "type": "image",
        "content": "example_uv_bad_full.png"
    },
    {
        "type": "image",
        "content": "example_uv_bad_close.png"
    },
    {
        "type": "image",
        "content": "example_uv_bad_layout.png"
    },
    {
        "type": "text",
        "content": "\n【UV质量评估标准】\n\n1. 结构与合理性（uv_score，35分）\n- 高分（28~35）： UV 岛（Islands）走向完全顺应 3D 形体结构，关键边缘（如长条、方正部件）进行了正交对齐（水平/垂直）；无由于解算错误导致的怪异畸形。\n- 低分（0~15）： 走向完全混乱，没有基本的几何逻辑；边缘呈严重的锯齿状、波浪状，完全无法进行方向性材质纹理（如拉丝、布纹）的平铺。\n\n2. 变形、拉伸与接缝（distortion_score，35分）\n- 高分（28~35）： 棋盘格大小分布均匀，无明显挤压或拉伸变形；缝合线（Seams）隐藏在视觉盲区或自然接缝处，重点视觉区域（如面部）可适当调高密度，但过渡自然。\n- 低分（0~15）： 棋盘格拉伸严重、扭曲变形；疏密差异过大导致严重的视觉分辨率不匹配；接缝杂乱且直接暴露在核心视觉区域。\n\n3. 排布、重叠与间距（packing_score，30分）\n- 高分（24~30）： 空间利用率（Packing Efficiency）高，空白浪费少；非故意镜像（Mirroring）情况下绝无 UV 岛交叉重叠（Overlapping）；留有足够的通道间距（Padding/Margin），防止像素溢出。\n- 低分（0~12）： UV 岛之间出现灾难性的重叠、交叉；间距几乎为零导致严重漏色；或大面积空白，严重浪费贴图分辨率。\n\n【分类规则】\n- good: 85 ~ 100  UV 规整，对齐良好，无拉伸扭曲，无异常重叠，间距合理，空间利用率高。\n- medium: 55 ~ 84   轻微拉伸或小范围扭曲，排列稍显松散或局部有轻微对齐问题，整体可用。\n- bad: 0 ~ 54    存在严重拉伸、大面积扭曲、UV 岛交叉重叠、排布极度混乱或边缘畸变。【输出严格按以下格式】\n{\n  \"score\": 0~100,\n  \"uv_score\": 0~50,\n  \"uniformity_score\": 0~50,\n  \"grade\": \"good/medium/bad\",\n  \"issues\": []\n}"
    },
    {
        "type": "input_image",
        "content": "checkerboard_all.png"
    },
    {
        "type": "input_image",
        "content": "checkerboard_closeup_all.png"
    },
    {
        "type": "input_image",
        "content": "checkerboard_uv_layout.png"
    }
]

OUTPUT_SPEC = [
    {
        "name": "score",
        "type": "int",
        "description": "表面规整度总分 0-100"
    },
    {
        "name": "uv_score",
        "type": "int",
        "description": "UV合理性 0-50"
    },
    {
        "name": "uniformity_score",
        "type": "int",
        "description": "均匀度与接缝 0-50"
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
