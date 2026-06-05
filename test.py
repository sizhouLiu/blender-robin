#!/usr/bin/env python3
"""
Standalone inference script for model: gemini-3.1-pro-preview-m-high-t-low
Generated from CapArena task (storage_dir: 细节丰富度v4)

Setup:
    pip install bce-python-sdk httpx Pillow

Environment variables required:
    BOS_ENDPOINT      - BOS endpoint (e.g. bj.bcebos.com)
    BOS_ACCESS_KEY    - BOS access key
    BOS_SECRET_KEY    - BOS secret key
    DEERAPI_BASE_URL  - DeerAPI base URL (e.g. https://api.deerapi.com)
    DEERAPI_KEY       - DeerAPI API key
"""

import os
import json
import base64
import asyncio
import time
import logging
import sys
import tempfile

import httpx
from PIL import Image
from baidubce.bce_client_configuration import BceClientConfiguration
from baidubce.auth.bce_credentials import BceCredentials
from baidubce.services.bos.bos_client import BosClient

# Load .env file if exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================================================
# Configuration
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
# Logging
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================================
# BOS helpers
# ============================================================================

def _get_bos_client():
    config = BceClientConfiguration(
        credentials=BceCredentials(BOS_ACCESS_KEY, BOS_SECRET_KEY),
        endpoint=BOS_ENDPOINT,
    )
    return BosClient(config)


_bos_client = _get_bos_client()


def bos_read_bytes(bos_path: str) -> bytes:
    """Read a file from BOS. bos_path format: bos://bucket/key"""
    parts = bos_path.replace("bos://", "").split("/", 1)
    bucket, key = parts[0], parts[1]
    data = _bos_client.get_object_as_string(bucket, key)
    if isinstance(data, str):
        return data.encode("latin-1")
    return data


def bos_read_json(bos_path: str) -> dict:
    """Read a JSON file from BOS."""
    parts = bos_path.replace("bos://", "").split("/", 1)
    bucket, key = parts[0], parts[1]
    data = _bos_client.get_object_as_string(bucket, key)
    return json.loads(data)


def bos_write_json(bos_path: str, data: dict):
    """Write a JSON file to BOS."""
    parts = bos_path.replace("bos://", "").split("/", 1)
    bucket, key = parts[0], parts[1]
    _bos_client.put_object_from_string(bucket, key, json.dumps(data, ensure_ascii=False, indent=2))


def bos_exists(bos_path: str) -> bool:
    """Check if a file exists on BOS."""
    parts = bos_path.replace("bos://", "").split("/", 1)
    bucket, key = parts[0], parts[1]
    try:
        response = _bos_client.list_objects(bucket, prefix=key, max_keys=1)
        if hasattr(response, "contents") and response.contents:
            return response.contents[0].key == key
        return False
    except Exception:
        return False

# ============================================================================
# Input file preprocessor
# ============================================================================

def preprocess_input_file(local_path: str) -> str:
    """
    Preprocess an input file before sending to the model.
    Accepts a local file path, returns a (possibly different) local file path.

    Default: converts RGBA PNG/WebP images to RGB with white background.
    Override this function to add your own preprocessing logic.
    """
    try:
        img = Image.open(local_path)
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            tmp = tempfile.NamedTemporaryFile(suffix=".webp", delete=False)
            background.save(tmp.name, "WEBP", lossless=True)
            return tmp.name
    except Exception:
        pass  # Not an image or cannot be processed, return as-is
    return local_path

# ============================================================================
# Auto-generated helpers (no need to edit per task)
# ============================================================================

def _parse_storage_location():
    """从 GLOBAL_FILE_* 变量推导 bucket 和 storage_dir。"""
    for var_name, var_value in globals().items():
        if var_name.startswith("GLOBAL_FILE_") and isinstance(var_value, str) and var_value.startswith("bos://"):
            # bos://bucket/storage_dir/global/filename
            parts = var_value.replace("bos://", "").split("/")
            if len(parts) >= 3 and parts[-2] == "global":
                bucket = parts[0]
                storage_dir = "/".join(parts[1:-2])
                return bucket, storage_dir
    raise ValueError("无法从 GLOBAL_FILE_* 变量推导 BOS 路径结构")


def _extract_input_filenames():
    """从 PROMPT_TEMPLATE 提取 input_image 文件名列表。"""
    filenames = []
    for item in PROMPT_TEMPLATE:
        if item.get("type") == "input_image":
            filenames.append(item["content"])
    return filenames


_BUCKET, _STORAGE_DIR = _parse_storage_location()
_INPUT_FILENAMES = _extract_input_filenames()
logger.info(f"Auto-detected: bucket={_BUCKET}, storage_dir={_STORAGE_DIR}")
logger.info(f"Input filenames: {_INPUT_FILENAMES}")


def load_case_ids() -> list:
    """列出 BOS {storage_dir}/input/ 下的所有子目录名作为 case IDs。"""
    prefix = f"{_STORAGE_DIR}/input/"
    case_ids = set()
    marker = None
    while True:
        kwargs = {"bucket_name": _BUCKET, "prefix": prefix, "delimiter": "/", "max_keys": 1000}
        if marker:
            kwargs["marker"] = marker
        response = _bos_client.list_objects(**kwargs)
        if hasattr(response, "common_prefixes") and response.common_prefixes:
            for cp in response.common_prefixes:
                case_id = cp.prefix.rstrip("/").split("/")[-1]
                case_ids.add(case_id)
        if response.is_truncated:
            marker = response.next_marker
        else:
            break
    logger.info(f"Found {len(case_ids)} case(s) under {prefix}")
    return sorted(case_ids)


def get_input_files(case_id: str) -> dict:
    """根据 case_id 和 PROMPT_TEMPLATE 中的 input_image 自动生成文件路径映射。"""
    return {
        filename: f"bos://{_BUCKET}/{_STORAGE_DIR}/input/{case_id}/{filename}"
        for filename in _INPUT_FILENAMES
    }


def get_output_path(case_id: str) -> str:
    """生成输出 JSON 的 BOS 路径。"""
    return f"bos://{_BUCKET}/{_STORAGE_DIR}/output/{case_id}.json"

# ============================================================================
# Prompt builder
# ============================================================================

def _download_and_preprocess(bos_path: str, suffix: str = ".png") -> bytes:
    """Download a file from BOS, preprocess it, and return the processed bytes."""
    raw_data = bos_read_bytes(bos_path)
    tmp_in = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_in.write(raw_data)
    tmp_in.close()
    processed_path = preprocess_input_file(tmp_in.name)
    with open(processed_path, "rb") as f:
        result = f.read()
    # Clean up temp files
    if os.path.exists(tmp_in.name):
        os.unlink(tmp_in.name)
    if processed_path != tmp_in.name and os.path.exists(processed_path):
        os.unlink(processed_path)
    return result


def check_input_files_exist(case_id: str) -> bool:
    """检查 case 的所有输入文件是否在 BOS 上存在。"""
    input_files = get_input_files(case_id)
    for filename, bos_path in input_files.items():
        if not bos_exists(bos_path):
            return False
    return True


def build_prompt(case_id: str) -> list:
    """Build resolved prompt parts for a case, reading images from BOS."""
    input_files = get_input_files(case_id)
    parts = []
    for tmpl in PROMPT_TEMPLATE:
        if tmpl["type"] == "text":
            parts.append({"type": "text", "content": tmpl["content"]})
        elif tmpl["type"] == "image":
            # Global image - read from BOS using global file path variables
            global_var = "GLOBAL_FILE_" + tmpl["content"].replace(".", "_").replace("-", "_").replace(" ", "_")
            bos_path = globals().get(global_var)
            if bos_path is None:
                raise ValueError(f"Global file variable {global_var} not found")
            suffix = os.path.splitext(tmpl["content"])[1] or ".png"
            image_data = _download_and_preprocess(bos_path, suffix)
            parts.append({"type": "image", "content": image_data})
        elif tmpl["type"] == "input_image":
            filename = tmpl["content"]
            bos_path = input_files.get(filename)
            if bos_path is None:
                raise ValueError(f"Input file {filename} not found for case {case_id}")
            suffix = os.path.splitext(filename)[1] or ".png"
            image_data = _download_and_preprocess(bos_path, suffix)
            parts.append({"type": "input_image", "content": image_data})
    return parts

# ============================================================================
# API caller (gemini-3.1-pro-preview-m-high-t-low - Gemini via DeerAPI)
# ============================================================================

OUTPUT_SCHEMA = {"type": "OBJECT", "properties": {
        "score": {"type": "INTEGER", "description": "\u7ec6\u8282\u4e30\u5bcc\u5ea6\u603b\u5206 0-100"},        "info_score": {"type": "INTEGER", "description": "\u7ec6\u8282\u4fe1\u606f\u91cf 0-60"},        "layer_score": {"type": "INTEGER", "description": "\u5c42\u6b21\u533a\u5206\u5ea6 0-40"},        "style": {"type": "STRING", "description": "\u6a21\u578b\u98ce\u683c\uff1a\u5199\u5b9e/\u5361\u901a/\u6781\u7b80/\u5de5\u4e1a"},        "asset_type": {"type": "STRING", "description": "\u8d44\u4ea7\u7c7b\u578b\uff1a\u89d2\u8272/\u9053\u5177/\u573a\u666f"},        "grade": {"type": "STRING", "description": "good/medium/bad"},        "issues": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "\u6263\u5206\u539f\u56e0"}
    }, "required": ["score", "info_score", "layer_score", "style", "asset_type", "grade", "issues"]}


async def call_api(case_id: str) -> dict:
    """Call Gemini API for a single case and return parsed output."""
    prompt_parts = build_prompt(case_id)

    # Build parts
    parts = []
    for part in prompt_parts:
        if part["type"] == "text":
            parts.append({"text": part["content"]})
        elif part["type"] in ("image", "input_image"):
            image_data = part["content"]
            if isinstance(image_data, bytes):
                b64_data = base64.b64encode(image_data).decode()
            else:
                b64_data = image_data
            parts.append({
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": b64_data,
                }
            })

    request_body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": OUTPUT_SCHEMA,
            "mediaResolution": "MEDIA_RESOLUTION_HIGH",
            "thinkingConfig": {
                "thinkingLevel": "LOW",
            },
        },
    }

    base_model = "gemini-3.1-pro-preview"
    url = f"{DEERAPI_BASE_URL}/v1beta/models/{base_model}:generateContent"

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {DEERAPI_KEY}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
        response.raise_for_status()
        result = response.json()

    # Extract text from response
    output_text = None
    candidates = result.get("candidates", [])
    if candidates:
        content = candidates[0].get("content", {})
        for p in content.get("parts", []):
            if "text" in p:
                output_text = p["text"]
                break

    if not output_text:
        raise ValueError("No output text in Gemini response")

    return json.loads(output_text)

# ============================================================================
# Result checker (resume support)
# ============================================================================

def check_exists(case_id: str) -> bool:
    """Check if output already exists for this case (for resume support)."""
    output_path = get_output_path(case_id)
    return bos_exists(output_path)


# ============================================================================
# Process a single case with retry
# ============================================================================

async def process_case(case_id: str, semaphore: asyncio.Semaphore, stats: dict):
    """Process a single case: call API, save result, retry on failure."""
    async with semaphore:
        if not check_input_files_exist(case_id):
            logger.warning(f"Case {case_id} skipped: input files missing on BOS")
            stats["skipped"] += 1
            return
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = await call_api(case_id)
                output_path = get_output_path(case_id)
                bos_write_json(output_path, result)
                stats["success"] += 1
                return
            except Exception as e:
                if attempt < MAX_RETRIES:
                    logger.warning(f"Case {case_id} failed (attempt {attempt}/{MAX_RETRIES}): {e}")
                    stats["retrying"] += 1
                    await asyncio.sleep(2 ** attempt)  # exponential backoff
                    stats["retrying"] -= 1
                else:
                    logger.error(f"Case {case_id} failed after {MAX_RETRIES} attempts: {e}")
                    stats["failed"] += 1
                    stats["failed_cases"].append(case_id)


# ============================================================================
# Progress display
# ============================================================================

def _fmt_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    elif s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    elif s < 86400:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    else:
        return f"{s // 86400}d{(s % 86400) // 3600:02d}h"


def print_progress(stats: dict, total: int, start_time: float):
    """Print progress bar with ETA."""
    done = stats["success"] + stats["failed"] + stats["skipped"]
    remaining = total - done
    elapsed = time.time() - start_time
    active_done = stats["success"] + stats["failed"]
    if active_done > 0:
        eta = elapsed / active_done * remaining
        eta_str = _fmt_duration(eta)
    else:
        eta_str = "..."
    elapsed_str = _fmt_duration(elapsed)
    sys.stdout.write(
        f"\r[{done}/{total}] elapsed: {elapsed_str} | eta: {eta_str} | "
        f"success: {stats['success']}, failed: {stats['failed']}, "
        f"skipped: {stats['skipped']}, retrying: {stats['retrying']}  "
    )
    sys.stdout.flush()


# ============================================================================
# Main
# ============================================================================

async def main():
    logger.info(f"Starting inference for model: {MODEL_NAME}")
    logger.info(f"RPM: {RPM}, MAX_CONCURRENT: {MAX_CONCURRENT}, MAX_RETRIES: {MAX_RETRIES}")

    # Load case IDs
    all_case_ids = load_case_ids()
    total = len(all_case_ids)
    logger.info(f"Total cases: {total}")

    # Stats tracking
    stats = {"success": 0, "failed": 0, "retrying": 0, "skipped": 0, "failed_cases": []}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    start_time = time.time()

    # Dispatch tasks, checking existence inline (no RPM delay for skips)
    delay = 60.0 / RPM
    tasks = []
    dispatched = 0
    for case_id in all_case_ids:
        if check_exists(case_id):
            stats["skipped"] += 1
            continue
        # Only rate-limit actual API dispatches
        if dispatched > 0:
            await asyncio.sleep(delay)
        task = asyncio.create_task(process_case(case_id, semaphore, stats))
        tasks.append(task)
        dispatched += 1
        print_progress(stats, total, start_time)

    if dispatched == 0:
        logger.info("Nothing to do. All cases already completed.")
        return

    if stats["skipped"] > 0:
        logger.info(f"Skipped {stats['skipped']} already-completed cases (resume mode)")
    logger.info(f"Cases to process: {dispatched}")

    # Wait for all tasks to complete
    await asyncio.gather(*tasks)
    print_progress(stats, total, start_time)
    print()  # newline after progress

    # Summary
    elapsed = time.time() - start_time
    logger.info(f"Done in {_fmt_duration(elapsed)}. Success: {stats['success']}, Failed: {stats['failed']}, Skipped: {stats['skipped']}")
    if stats["failed_cases"]:
        logger.info(f"Failed case IDs: {stats['failed_cases']}")


if __name__ == "__main__":
    asyncio.run(main())
