#!/usr/bin/env python3
"""通用打分引擎 - 支持任意评分任务"""

import os
import json
import base64
import asyncio
import time
import logging
import sys
import tempfile
from pathlib import Path

import httpx
from PIL import Image
from baidubce.bce_client_configuration import BceClientConfiguration
from baidubce.auth.bce_credentials import BceCredentials
from baidubce.services.bos.bos_client import BosClient


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
# BOS Client & Helpers
# ============================================================================

def get_bos_client(endpoint, access_key, secret_key):
    """Create BOS client."""
    config = BceClientConfiguration(
        credentials=BceCredentials(access_key, secret_key),
        endpoint=endpoint,
    )
    return BosClient(config)


def bos_read_bytes(client, bos_path: str) -> bytes:
    """Read file from BOS. bos_path: bos://bucket/key"""
    parts = bos_path.replace("bos://", "").split("/", 1)
    bucket, key = parts[0], parts[1]
    data = client.get_object_as_string(bucket, key)
    if isinstance(data, str):
        return data.encode("latin-1")
    return data


def bos_write_json(client, bos_path: str, data: dict):
    """Write JSON to BOS."""
    parts = bos_path.replace("bos://", "").split("/", 1)
    bucket, key = parts[0], parts[1]
    client.put_object_from_string(bucket, key, json.dumps(data, ensure_ascii=False))


def bos_exists(client, bos_path: str) -> bool:
    """Check if file exists."""
    parts = bos_path.replace("bos://", "").split("/", 1)
    bucket, key = parts[0], parts[1]
    try:
        response = client.list_objects(bucket, prefix=key, max_keys=1)
        if hasattr(response, "contents") and response.contents:
            return response.contents[0].key == key
        return False
    except Exception:
        return False


def parse_storage_location(global_file_paths: dict) -> tuple:
    """Parse bucket/storage_dir from GLOBAL_FILE_* dict."""
    for path in global_file_paths.values():
        if path.startswith("bos://"):
            path_no_scheme = path.replace("bos://", "")
            bucket = path_no_scheme.split("/")[0]
            parts = path_no_scheme.split("/")
            if len(parts) >= 3 and parts[-2] == "global":
                storage_dir = "/".join(parts[1:-2])
                return bucket, storage_dir
    raise ValueError("Cannot parse bucket/storage_dir from global file paths")


def extract_input_filenames(prompt_template: list) -> list:
    """Extract input_image filenames from prompt template."""
    return [item["content"] for item in prompt_template if item.get("type") == "input_image"]


_SPEC_TYPE_MAP = {
    "int":      ("INTEGER", False),
    "float":    ("NUMBER",  False),
    "string":   ("STRING",  False),
    "str":      ("STRING",  False),
    "bool":     ("BOOLEAN", False),
    "list[str]": ("STRING", True),
    "list[int]": ("INTEGER", True),
    "list[float]": ("NUMBER", True),
}

def spec_to_schema(output_spec: list) -> dict:
    """Convert OUTPUT_SPEC list to Gemini responseSchema dict."""
    if isinstance(output_spec, dict):
        return output_spec  # already a raw schema, pass through
    properties = {}
    required = []
    for field in output_spec:
        name = field["name"]
        raw_type = field.get("type", "string").lower().strip()
        desc = field.get("description", "")
        gemini_type, is_array = _SPEC_TYPE_MAP.get(raw_type, ("STRING", False))
        if is_array:
            properties[name] = {
                "type": "ARRAY",
                "items": {"type": gemini_type},
                "description": desc,
            }
        else:
            properties[name] = {"type": gemini_type, "description": desc}
        required.append(name)
    return {"type": "OBJECT", "properties": properties, "required": required}


# ============================================================================
# Image preprocessing
# ============================================================================

def preprocess_input_file(input_path: str) -> str:
    """Preprocess image: resize if needed."""
    img = Image.open(input_path)
    max_dim = 2048
    if max(img.width, img.height) > max_dim:
        ratio = max_dim / max(img.width, img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    output_path = input_path.replace(".", "_processed.")
    img.save(output_path, format="PNG")
    return output_path


def download_and_preprocess(client, bos_path: str, suffix: str = ".png") -> bytes:
    """Download from BOS, preprocess, return bytes."""
    raw_data = bos_read_bytes(client, bos_path)
    tmp_in = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_in.write(raw_data)
    tmp_in.close()
    processed_path = preprocess_input_file(tmp_in.name)
    with open(processed_path, "rb") as f:
        result = f.read()
    os.unlink(tmp_in.name)
    os.unlink(processed_path)
    return result


# ============================================================================
# Prompt Builder
# ============================================================================

def build_prompt(
    client,
    case_id: str,
    bucket: str,
    storage_dir: str,
    prompt_template: list,
    global_file_paths: dict,
    input_filenames: list,
) -> list:
    """Build resolved prompt for a case."""
    input_files = {
        filename: f"bos://{bucket}/{storage_dir}/input/{case_id}/{filename}"
        for filename in input_filenames
    }

    parts = []
    for tmpl in prompt_template:
        if tmpl["type"] == "text":
            parts.append({"type": "text", "content": tmpl["content"]})
        elif tmpl["type"] == "image":
            global_var_name = "GLOBAL_FILE_" + tmpl["content"].replace(".", "_").replace("-", "_").replace(" ", "_")
            bos_path = global_file_paths.get(global_var_name)
            if not bos_path:
                raise ValueError(f"Global file {global_var_name} not found")
            suffix = Path(tmpl["content"]).suffix or ".png"
            image_data = download_and_preprocess(client, bos_path, suffix)
            parts.append({"type": "image", "content": image_data})
        elif tmpl["type"] == "input_image":
            filename = tmpl["content"]
            bos_path = input_files[filename]
            suffix = Path(filename).suffix or ".png"
            image_data = download_and_preprocess(client, bos_path, suffix)
            parts.append({"type": "input_image", "content": image_data})

    return parts


# ============================================================================
# API Call
# ============================================================================

async def call_api(
    case_id: str,
    client,
    bucket: str,
    storage_dir: str,
    prompt_template: list,
    global_file_paths: dict,
    input_filenames: list,
    output_schema: dict,
    model_name: str,
    deerapi_base_url: str,
    deerapi_key: str,
) -> dict:
    """Call Gemini API for a single case."""
    prompt_parts = await asyncio.to_thread(
        build_prompt,
        client, case_id, bucket, storage_dir,
        prompt_template, global_file_paths, input_filenames
    )

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
            parts.append({"inline_data": {"mime_type": "image/png", "data": b64_data}})

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": spec_to_schema(output_schema),
        },
    }

    url = f"{deerapi_base_url}/v1beta/models/{model_name}:generateContent"
    headers = {"x-goog-api-key": deerapi_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=180) as http_client:
        response = await http_client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()

    output_text = None
    candidates = result.get("candidates", [])
    if candidates:
        content = candidates[0].get("content", {})
        for p in content.get("parts", []):
            if "text" in p:
                output_text = p["text"]
                break

    if not output_text:
        raise ValueError("No output text in API response")

    return json.loads(output_text)


# ============================================================================
# Case Processing
# ============================================================================

def check_input_files_exist(client, case_id: str, bucket: str, storage_dir: str, input_filenames: list) -> bool:
    """Check if all input files exist."""
    for filename in input_filenames:
        bos_path = f"bos://{bucket}/{storage_dir}/input/{case_id}/{filename}"
        if not bos_exists(client, bos_path):
            return False
    return True


def check_output_exists(client, case_id: str, bucket: str, storage_dir: str, output_subdir: str = "") -> bool:
    """Check if output already exists."""
    subdir = f"{output_subdir}/" if output_subdir else ""
    output_path = f"bos://{bucket}/{storage_dir}/output/{subdir}{case_id}.json"
    return bos_exists(client, output_path)


async def process_case(
    case_id: str,
    semaphore: asyncio.Semaphore,
    stats: dict,
    client,
    bucket: str,
    storage_dir: str,
    prompt_template: list,
    global_file_paths: dict,
    input_filenames: list,
    output_schema: dict,
    model_name: str,
    deerapi_base_url: str,
    deerapi_key: str,
    max_retries: int,
    output_subdir: str = "",
):
    """Process a single case with retry."""
    async with semaphore:
        if not check_input_files_exist(client, case_id, bucket, storage_dir, input_filenames):
            logger.warning(f"Case {case_id} skipped: input files missing")
            stats["skipped"] += 1
            return

        for attempt in range(1, max_retries + 1):
            try:
                result = await call_api(
                    case_id, client, bucket, storage_dir,
                    prompt_template, global_file_paths, input_filenames,
                    output_schema, model_name, deerapi_base_url, deerapi_key
                )
                subdir = f"{output_subdir}/" if output_subdir else ""
                output_path = f"bos://{bucket}/{storage_dir}/output/{subdir}{case_id}.json"
                bos_write_json(client, output_path, result)
                stats["success"] += 1
                return
            except Exception as e:
                import traceback
                detail = str(e) or repr(e)
                if hasattr(e, "response"):
                    try:
                        detail += f" | HTTP {e.response.status_code}: {e.response.text[:500]}"
                    except Exception:
                        pass
                if attempt < max_retries:
                    logger.warning(f"Case {case_id} failed (attempt {attempt}/{max_retries}): {detail}")
                    stats["retrying"] += 1
                    await asyncio.sleep(2 ** attempt)
                    stats["retrying"] -= 1
                else:
                    logger.error(f"Case {case_id} failed after {max_retries} attempts: {detail}\n{traceback.format_exc()}")
                    stats["failed"] += 1
                    stats["failed_cases"].append(case_id)


def load_case_ids(client, bucket: str, storage_dir: str) -> list:
    """List all case IDs under input/."""
    prefix = f"{storage_dir}/input/"
    case_ids = set()
    marker = None
    while True:
        kwargs = {"bucket_name": bucket, "prefix": prefix, "delimiter": "/", "max_keys": 1000}
        if marker:
            kwargs["marker"] = marker
        response = client.list_objects(**kwargs)
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


# ============================================================================
# Main Runner
# ============================================================================

async def run_scoring(
    bos_endpoint: str,
    bos_access_key: str,
    bos_secret_key: str,
    deerapi_base_url: str,
    deerapi_key: str,
    model_name: str,
    rpm: int,
    max_retries: int,
    max_concurrent: int,
    global_file_paths: dict,
    prompt_template: list,
    output_schema: dict,
    output_subdir: str | None = None,
):
    """Main scoring loop.

    output_subdir: subdirectory under output/ for this task's results.
    Defaults to the stem of the calling script's filename (e.g. '细节丰富度').
    """
    import inspect
    if output_subdir is None:
        caller_frame = inspect.stack()[1]
        output_subdir = Path(caller_frame.filename).stem
    client = get_bos_client(bos_endpoint, bos_access_key, bos_secret_key)

    bucket, storage_dir = parse_storage_location(global_file_paths)
    input_filenames = extract_input_filenames(prompt_template)

    logger.info(f"Auto-detected: bucket={bucket}, storage_dir={storage_dir}")
    logger.info(f"Input filenames: {input_filenames}")
    logger.info(f"Starting inference for model: {model_name}")
    logger.info(f"RPM: {rpm}, MAX_CONCURRENT: {max_concurrent}, MAX_RETRIES: {max_retries}")

    case_ids = load_case_ids(client, bucket, storage_dir)
    logger.info(f"Total cases: {len(case_ids)}, checking for existing outputs (resume mode)...")

    # 并发检查哪些已有输出，避免串行 BOS 调用在大量 case 下耗时过长
    check_sem = asyncio.Semaphore(20)

    async def _exists_async(cid: str) -> bool:
        async with check_sem:
            return await asyncio.to_thread(check_output_exists, client, cid, bucket, storage_dir, output_subdir)

    exists_flags = await asyncio.gather(*[_exists_async(cid) for cid in case_ids])
    pending = [cid for cid, done in zip(case_ids, exists_flags) if not done]
    skipped_count = len(case_ids) - len(pending)

    logger.info(f"Resume: {skipped_count} already done, {len(pending)} pending")

    if not pending:
        logger.info("Nothing to do. All cases already completed.")
        return

    stats = {
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "retrying": 0,
        "failed_cases": [],
    }

    semaphore = asyncio.Semaphore(max_concurrent)
    # Token bucket: refill 1 token every (60/rpm) seconds
    rate_interval = 60.0 / rpm
    rate_lock = asyncio.Lock()
    next_allowed = [time.monotonic()]

    async def rate_limited_process(case_id):
        async with rate_lock:
            now = time.monotonic()
            wait = next_allowed[0] - now
            if wait > 0:
                await asyncio.sleep(wait)
            next_allowed[0] = max(next_allowed[0], time.monotonic()) + rate_interval
        await process_case(
            case_id, semaphore, stats, client, bucket, storage_dir,
            prompt_template, global_file_paths, input_filenames,
            output_schema, model_name, deerapi_base_url, deerapi_key, max_retries, output_subdir
        )

    start_time = time.monotonic()

    async def tracked(case_id):
        await rate_limited_process(case_id)
        elapsed = time.monotonic() - start_time
        completed = stats["success"] + stats["failed"] + stats["skipped"]
        rate = completed / elapsed * 60 if elapsed > 0 else 0
        eta = (len(pending) - completed) / rate * 60 if rate > 0 else 0
        eta_str = f"{int(eta // 3600)}h{int((eta % 3600) // 60)}m{int(eta % 60)}s" if eta > 0 else "..."
        sys.stdout.write(
            f"\r[{completed}/{len(pending)}] elapsed: {int(elapsed // 60)}m{int(elapsed % 60)}s | "
            f"eta: {eta_str} | success: {stats['success']}, failed: {stats['failed']}, "
            f"skipped: {stats['skipped']}, retrying: {stats['retrying']}  "
        )
        sys.stdout.flush()

    await asyncio.gather(*[tracked(cid) for cid in pending])

    print()
    logger.info(f"Completed: {stats['success']} success, {stats['failed']} failed, {stats['skipped']} skipped")
    if stats["failed_cases"]:
        logger.info(f"Failed cases: {stats['failed_cases'][:10]}...")
