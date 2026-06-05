#!/usr/bin/env python3
"""列出 BOS bucket 中指定前缀下的文件"""
import sys
from dotenv import load_dotenv
load_dotenv()

import os
from baidubce.services.bos.bos_client import BosClient
from baidubce.auth.bce_credentials import BceCredentials
from baidubce.bce_client_configuration import BceClientConfiguration

bucket = sys.argv[1] if len(sys.argv) > 1 else "uvtest"
prefix = sys.argv[2] if len(sys.argv) > 2 else "robin_renders/rgb_closeup/input/"

client = BosClient(BceClientConfiguration(
    credentials=BceCredentials(
        os.environ["BOS_ACCESS_KEY"],
        os.environ["BOS_SECRET_KEY"]
    ),
    endpoint=os.environ["BOS_ENDPOINT"].replace("https://", "").replace("http://", ""),
))

print(f"Listing: bos://{bucket}/{prefix}")
print("-" * 80)

marker = None
count = 0
max_show = 50  # 只显示前 50 个

while count < max_show:
    kwargs = {"bucket_name": bucket, "prefix": prefix, "max_keys": 100}
    if marker:
        kwargs["marker"] = marker

    resp = client.list_objects(**kwargs)

    if hasattr(resp, "contents") and resp.contents:
        for obj in resp.contents:
            if count >= max_show:
                break
            print(f"{obj.key}  ({obj.size} bytes)")
            count += 1

    if resp.is_truncated:
        marker = resp.next_marker
    else:
        break

print(f"\n显示了前 {count} 个文件")
print(f"\n用法: python list_bos.py [bucket] [prefix]")
print(f"示例: python list_bos.py uvtest robin_renders/rgb_closeup/input/case_001/")
