
"""
BOS 模型拉取模块 (ported from datachain-cli-tasks).

提供从百度对象存储 (BOS) 按 manifest 批量下载 3D 模型的能力，供
可视化终端 (robin_interactive.py) 的「从 BOS 拉取并渲染」流程使用。

依赖:
    bce-python-sdk   (提供 baidubce SDK, BOSClient 必需)
    python-dotenv    (可选, 读取 .env; 缺失时回退到手动解析)

环境变量 (可写在 .env):
    BOS_ENDPOINT     例如 https://xxx.bcebos.com
    BOS_ACCESS_KEY
    BOS_SECRET_KEY
"""
from __future__ import annotations

import json
import os
import re
import time
import traceback
from functools import wraps
from typing import Callable, Optional

MAX_RETRIES = int(os.environ.get("BOS_MAX_RETRIES", 3))

# 需要同捆下载外部依赖文件 (贴图/材质等) 的格式
FORMATS_WITH_DEPENDENCIES = frozenset({"gltf", "obj", "dae", "fbx"})
MAX_SIBLING_FILES = 200


def _retry(max_retries: int = MAX_RETRIES, retry_delay: int = 1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception:
                    retries += 1
                    if retries > max_retries:
                        raise
                    print(f"  [BOS] {func.__name__} 第 {retries}/{max_retries} 次重试...")
                    print(traceback.format_exc())
                    time.sleep(retry_delay)
        return wrapper
    return decorator


class BOSClient:
    """百度 BOS 客户端封装 (ported from example-bos/bos.py)。"""

    def __init__(self):
        from baidubce.services.bos.bos_client import BosClient
        from baidubce.auth.bce_credentials import BceCredentials
        from baidubce.bce_client_configuration import BceClientConfiguration

        endpoint = os.getenv("BOS_ENDPOINT")
        access_key = os.getenv("BOS_ACCESS_KEY")
        secret_key = os.getenv("BOS_SECRET_KEY")
        config = BceClientConfiguration(
            credentials=BceCredentials(
                access_key_id=access_key,
                secret_access_key=secret_key,
            ),
            endpoint=endpoint,
        )
        self.client = BosClient(config)

    @_retry()
    def get_file(self, bos_bucket: str, bos_path: str, file_path: str):
        self.client.get_object_to_file(bos_bucket, bos_path, file_path)

    @_retry()
    def list_objects(self, bos_bucket: str, prefix: str, max_keys: int = 1000):
        """列出 BOS 前缀下的所有对象 key, 支持分页。"""
        keys: list[str] = []
        marker = None
        while True:
            kwargs = {"prefix": prefix, "max_keys": min(1000, max_keys - len(keys))}
            if marker:
                kwargs["marker"] = marker
            response = self.client.list_objects(bos_bucket, **kwargs)
            contents = getattr(response, "contents", []) or []
            for obj in contents:
                keys.append(obj.key)
            if not getattr(response, "is_truncated", False) or len(keys) >= max_keys:
                break
            marker = keys[-1] if keys else None
        return keys


def decode_unicode_escapes(path: str) -> str:
    """将路径中的 uXXXX 格式转义还原为实际 Unicode 字符。"""
    return re.sub(r"u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), path)


def load_bos_env(env_path: str | os.PathLike = ".env") -> dict:
    """从 .env 加载 BOS 凭证并回填到 os.environ。返回已解析的键值。

    优先用 python-dotenv; 缺失时手动解析。
    """
    env_path = str(env_path)
    parsed: dict[str, Optional[str]] = {}
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
    except ImportError:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        os.environ.setdefault(
                            key.strip(), value.strip().strip('"').strip("'")
                        )
    for key in ("BOS_ENDPOINT", "BOS_ACCESS_KEY", "BOS_SECRET_KEY"):
        parsed[key] = os.getenv(key)
    return parsed


def _require_bos_env() -> None:
    missing = [
        k for k in ("BOS_ENDPOINT", "BOS_ACCESS_KEY", "BOS_SECRET_KEY")
        if not os.getenv(k)
    ]
    if missing:
        raise EnvironmentError(
            "缺少 BOS 配置: " + ", ".join(missing) + "\n"
            "请在 .env 文件或环境变量中提供 BOS_ENDPOINT / BOS_ACCESS_KEY / BOS_SECRET_KEY"
        )


def _local_path(output_base: str, source: str, uuid: str, bos_path: str) -> str:
    """本地保存路径规则: {output_base}/{source}/{uuid}/{原文件名}。"""
    file_name = os.path.basename(bos_path) or f"{uuid}.unknown"
    return os.path.join(output_base, source, uuid, file_name)


def _is_mac_junk(path: str) -> bool:
    return os.path.basename(path).startswith("._") or "/__MACOSX/" in path


def _download_sibling_files(
    client: "BOSClient", bos_bucket: str, bos_path: str,
    local_dir: str, log: Callable[[str], None],
) -> int:
    """下载同目录下的依赖文件 (gltf/obj/dae/fbx 等), 保留子目录结构。"""
    dir_prefix = bos_path.rsplit("/", 1)[0] + "/"
    try:
        sibling_keys = client.list_objects(
            bos_bucket, prefix=dir_prefix, max_keys=MAX_SIBLING_FILES
        )
    except Exception as e:
        log(f"  无法列出目录 {bos_bucket}/{dir_prefix}: {e}")
        return 0

    downloaded = 0
    for key in sibling_keys:
        if key == bos_path:
            continue
        relative_path = key[len(dir_prefix):]
        if not relative_path or _is_mac_junk(relative_path):
            continue
        local_file = os.path.join(local_dir, relative_path)
        if os.path.exists(local_file) and os.path.getsize(local_file) > 0:
            continue
        try:
            os.makedirs(os.path.dirname(local_file), exist_ok=True)
            client.get_file(bos_bucket=bos_bucket, bos_path=key, file_path=local_file)
            downloaded += 1
        except Exception as e:
            log(f"  依赖文件下载失败 {key}: {e}")
    return downloaded


def download_manifest(
    manifest: str | os.PathLike,
    output_base: str | os.PathLike,
    limit: Optional[int] = None,
    mapping_file: Optional[str | os.PathLike] = None,
    skip_existing: bool = True,
    log: Callable[[str], None] = print,
) -> dict:
    """按 manifest (JSON Lines) 从 BOS 批量下载模型到本地。

    manifest 每行格式: {"uuid", "old_bucket", "old_oss_path", "source"}
    本地路径规则: {output_base}/{source}/{uuid}/{原文件名}
    对 gltf/obj/dae/fbx 自动同捆下载依赖文件。

    返回统计 dict: {output_base, processed, success, skipped, failed}
    """
    _require_bos_env()
    manifest = str(manifest)
    output_base = str(output_base)
    if not os.path.exists(manifest):
        raise FileNotFoundError(f"manifest 文件不存在: {manifest}")

    client = BOSClient()
    if mapping_file:
        os.makedirs(os.path.dirname(str(mapping_file)) or ".", exist_ok=True)
        mapping_fp = open(mapping_file, "a", encoding="utf-8")
    else:
        mapping_fp = None

    stats = {"output_base": output_base, "processed": 0,
             "success": 0, "skipped": 0, "failed": 0}

    def _record(uuid, source, local, bucket, bos_path, status, reason=""):
        if mapping_fp is None:
            return
        mapping_fp.write(json.dumps({
            "uuid": uuid, "source": source, "local_path": local,
            "bucket": bucket, "bos_path": bos_path, "status": status,
            "reason": reason,
        }, ensure_ascii=False) + "\n")
        mapping_fp.flush()

    try:
        with open(manifest, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                if limit and stats["processed"] >= limit:
                    break

                try:
                    item = json.loads(line)
                except json.JSONDecodeError as e:
                    log(f"第 {line_num} 行 JSON 解析失败: {e}")
                    continue

                uuid = item.get("uuid")
                # 兼容两种字段名: bucket/bos_uri (新) 和 old_bucket/old_oss_path (旧)
                bucket = item.get("bucket") or item.get("old_bucket")
                bos_path = item.get("bos_uri") or item.get("old_oss_path")
                source = item.get("source", "unknown")

                if bos_path and _is_mac_junk(bos_path):
                    stats["processed"] += 1
                    stats["skipped"] += 1
                    _record(uuid or "", source, "", bucket or "",
                            bos_path or "", "skipped", "macOS 隐藏文件")
                    continue

                if bos_path and re.search(r"u[0-9a-fA-F]{4}", bos_path):
                    bos_path = decode_unicode_escapes(bos_path)

                if not uuid or not bucket or not bos_path:
                    stats["processed"] += 1
                    stats["failed"] += 1
                    _record(uuid or "", source, "", bucket or "",
                            bos_path or "", "failed", "缺少必要字段")
                    log(f"第 {line_num} 行缺少必要字段, 跳过")
                    continue

                local = _local_path(output_base, source, uuid, bos_path)

                # 断点续传: 本地已存在且非空则跳过
                if skip_existing and os.path.exists(local) and os.path.getsize(local) > 0:
                    stats["processed"] += 1
                    stats["success"] += 1
                    _record(uuid, source, local, bucket, bos_path, "success", "本地已存在")
                    _print_progress(stats, log)
                    continue

                os.makedirs(os.path.dirname(local), exist_ok=True)
                try:
                    client.get_file(bos_bucket=bucket, bos_path=bos_path, file_path=local)
                    ok = os.path.exists(local) and os.path.getsize(local) > 0
                except Exception as e:
                    log(f"下载失败 {bucket}/{bos_path}: {e}")
                    ok = False

                stats["processed"] += 1
                if ok:
                    stats["success"] += 1
                    ext = os.path.splitext(bos_path)[1].lstrip(".").lower()
                    if ext in FORMATS_WITH_DEPENDENCIES:
                        n = _download_sibling_files(
                            client, bucket, bos_path, os.path.dirname(local), log)
                        if n:
                            log(f"  额外下载 {n} 个依赖文件 ({ext})")
                    _record(uuid, source, local, bucket, bos_path, "success")
                else:
                    stats["failed"] += 1
                    if os.path.exists(local) and os.path.getsize(local) == 0:
                        os.remove(local)
                    _record(uuid, source, "", bucket, bos_path, "failed", "下载失败")
                _print_progress(stats, log)
    finally:
        if mapping_fp is not None:
            mapping_fp.close()

    return stats


def _print_progress(stats: dict, log: Callable[[str], None]) -> None:
    log(
        f"进度: 已处理={stats['processed']} | 成功={stats['success']} | "
        f"跳过={stats['skipped']} | 失败={stats['failed']}"
    )
