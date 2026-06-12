#!/usr/bin/env python3
"""评分结果可视化 Web 服务 - FastAPI"""

import os
import json
import io
import base64
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, Response
import uvicorn

from baidubce.bce_client_configuration import BceClientConfiguration
from baidubce.auth.bce_credentials import BceCredentials
from baidubce.services.bos.bos_client import BosClient

# ============================================================================
# BOS Client
# ============================================================================

def _get_bos_client():
    config = BceClientConfiguration(
        credentials=BceCredentials(
            os.environ["BOS_ACCESS_KEY"],
            os.environ["BOS_SECRET_KEY"]
        ),
        endpoint=os.environ["BOS_ENDPOINT"].replace("https://", "").replace("http://", ""),
    )
    return BosClient(config)


_bos_client = _get_bos_client()

# Defaults from env or hardcode
DEFAULT_BUCKET = os.environ.get("VIEW_BUCKET", "uv-test")
DEFAULT_PREFIX = os.environ.get("VIEW_PREFIX", "robin_renders/uv_check")
DEFAULT_SUBDIR = os.environ.get("VIEW_SUBDIR", "")

app = FastAPI(title="Score Viewer")


@app.on_event("startup")
async def preload_metadata():
    """Background preload all case metadata on startup."""
    import threading

    def _preload():
        bucket = DEFAULT_BUCKET
        prefix = DEFAULT_PREFIX
        subdir = DEFAULT_SUBDIR
        case_ids = bos_list_case_ids(bucket, prefix, subdir)
        logger.info(f"Preloading metadata for {len(case_ids)} cases...")
        loaded = 0
        for case_id in case_ids:
            get_case_metadata(bucket, prefix, subdir, case_id)
            loaded += 1
            if loaded % 100 == 0:
                logger.info(f"  Preloaded {loaded}/{len(case_ids)}")
        logger.info(f"Metadata preload complete: {loaded} cases cached")

    threading.Thread(target=_preload, daemon=True).start()


import logging as _logging
logger = _logging.getLogger(__name__)


# ============================================================================
# BOS Helpers
# ============================================================================

def bos_read_bytes(bucket: str, key: str) -> bytes:
    data = _bos_client.get_object_as_string(bucket, key)
    if isinstance(data, str):
        return data.encode("latin-1")
    return data


def bos_read_json(bucket: str, key: str) -> dict:
    data = _bos_client.get_object_as_string(bucket, key)
    return json.loads(data)


def bos_list_subdirs(bucket: str, prefix: str) -> list:
    """List immediate subdirectories under output/."""
    output_prefix = f"{prefix}/output/"
    subdirs = []
    response = _bos_client.list_objects(
        bucket_name=bucket, prefix=output_prefix, delimiter="/", max_keys=1000
    )
    if hasattr(response, "common_prefixes") and response.common_prefixes:
        for cp in response.common_prefixes:
            name = cp.prefix[len(output_prefix):].rstrip("/")
            if name:
                subdirs.append(name)
    return sorted(subdirs)


def bos_list_case_ids(bucket: str, prefix: str, subdir: str = "") -> list:
    """List all case IDs that have output JSON."""
    subdir_part = f"{subdir}/" if subdir else ""
    output_prefix = f"{prefix}/output/{subdir_part}"
    case_ids = []
    marker = None
    while True:
        kwargs = {"bucket_name": bucket, "prefix": output_prefix, "max_keys": 1000}
        if marker:
            kwargs["marker"] = marker
        response = _bos_client.list_objects(**kwargs)
        if hasattr(response, "contents") and response.contents:
            for obj in response.contents:
                if obj.key.endswith(".json"):
                    case_ids.append(Path(obj.key).stem)
        if response.is_truncated:
            marker = response.next_marker
        else:
            break
    return sorted(case_ids)


def bos_list_images(bucket: str, prefix: str, case_id: str) -> list:
    """List image files for a case."""
    input_prefix = f"{prefix}/input/{case_id}/"
    response = _bos_client.list_objects(bucket, prefix=input_prefix, max_keys=100)
    images = []
    if hasattr(response, "contents"):
        for obj in response.contents:
            if obj.key.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                images.append(obj.key)
    return images


# ============================================================================
# Lazy cache for case metadata (grade, score)
# ============================================================================

from datetime import datetime, timedelta

_metadata_cache = {}  # {(bucket, prefix, subdir, case_id): {"grade": ..., "score": ..., "expires": datetime}}
_CACHE_TTL = timedelta(minutes=5)

def get_case_metadata(bucket: str, prefix: str, subdir: str, case_id: str) -> dict:
    """Get case metadata with lazy cache."""
    key = (bucket, prefix, subdir, case_id)
    now = datetime.now()

    # Check cache
    if key in _metadata_cache:
        cached = _metadata_cache[key]
        if cached["expires"] > now:
            return {"grade": cached["grade"], "score": cached["score"]}

    # Cache miss or expired, read from BOS
    subdir_part = f"{subdir}/" if subdir else ""
    try:
        score_data = bos_read_json(bucket, f"{prefix}/output/{subdir_part}{case_id}.json")
        grade = score_data.get("grade")
        score = score_data.get("score", 0)

        # Store in cache
        _metadata_cache[key] = {
            "grade": grade,
            "score": score,
            "expires": now + _CACHE_TTL
        }
        return {"grade": grade, "score": score}
    except Exception:
        return {"grade": None, "score": 0}


# ============================================================================
# API Routes
# ============================================================================

@app.get("/api/cases")
def list_cases(
    bucket: Optional[str] = Query(default=None),
    prefix: Optional[str] = Query(default=None),
    subdir: Optional[str] = Query(default=None),
    grade: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    score_min: Optional[int] = Query(default=None),
    score_max: Optional[int] = Query(default=None),
    mark: Optional[str] = Query(default=None),
    page: int = Query(default=0),
    page_size: int = Query(default=20),
):
    """List scored cases with server-side pagination."""
    bucket = bucket or DEFAULT_BUCKET
    prefix = prefix or DEFAULT_PREFIX
    subdir = subdir if subdir is not None else DEFAULT_SUBDIR
    case_ids = bos_list_case_ids(bucket, prefix, subdir)
    subdir_part = f"{subdir}/" if subdir else ""

    # Load marks for mark filter
    marks = {}
    if mark:
        marks_key = f"{prefix}/marks/{subdir_part}marks.json"
        try:
            marks = bos_read_json(bucket, marks_key)
        except Exception:
            marks = {}

    # Filter by search first (cheap, no BOS calls)
    if search:
        case_ids = [cid for cid in case_ids if search.lower() in cid.lower()]

    # Filter by mark
    if mark:
        if mark == "agree":
            case_ids = [cid for cid in case_ids if marks.get(cid) == "agree"]
        elif mark == "disagree":
            case_ids = [cid for cid in case_ids if marks.get(cid) == "disagree"]
        elif mark == "unmarked":
            case_ids = [cid for cid in case_ids if cid not in marks or not marks.get(cid)]

    total_all = len(case_ids)

    # If grade or score filter is set, use cached metadata for filtering
    if grade or score_min is not None or score_max is not None:
        filtered = []
        for case_id in case_ids:
            meta = get_case_metadata(bucket, prefix, subdir, case_id)
            if grade and meta["grade"] != grade:
                continue
            if score_min is not None and meta["score"] < score_min:
                continue
            if score_max is not None and meta["score"] > score_max:
                continue
            filtered.append(case_id)
        case_ids = filtered
    else:
        # No filter needed
        pass

    total_filtered = len(case_ids)

    # Paginate
    start = page * page_size
    end = start + page_size
    page_ids = case_ids[start:end]

    # Only fetch details for current page
    results = []
    for case_id in page_ids:
        try:
            score_data = bos_read_json(bucket, f"{prefix}/output/{subdir_part}{case_id}.json")
        except Exception:
            continue
        images = [Path(k).name for k in bos_list_images(bucket, prefix, case_id)]
        results.append({"case_id": case_id, "images": images, **score_data})

    return {"total": total_filtered, "total_all": total_all, "page": page, "page_size": page_size, "cases": results}


@app.get("/api/case/{case_id}")
def get_case(
    case_id: str,
    bucket: Optional[str] = Query(default=None),
    prefix: Optional[str] = Query(default=None),
    subdir: Optional[str] = Query(default=None),
):
    """Get score and image list for a single case."""
    bucket = bucket or DEFAULT_BUCKET
    prefix = prefix or DEFAULT_PREFIX
    subdir = subdir if subdir is not None else DEFAULT_SUBDIR
    subdir_part = f"{subdir}/" if subdir else ""
    try:
        score_data = bos_read_json(bucket, f"{prefix}/output/{subdir_part}{case_id}.json")
    except Exception as e:
        return {"error": str(e)}

    images = bos_list_images(bucket, prefix, case_id)
    image_names = [Path(k).name for k in images]
    return {"case_id": case_id, "score": score_data, "images": image_names}


@app.get("/api/image/{case_id}/{filename}")
def get_image(
    case_id: str,
    filename: str,
    bucket: Optional[str] = Query(default=None),
    prefix: Optional[str] = Query(default=None),
):
    """Proxy an image from BOS."""
    bucket = bucket or DEFAULT_BUCKET
    prefix = prefix or DEFAULT_PREFIX
    key = f"{prefix}/input/{case_id}/{filename}"
    try:
        data = bos_read_bytes(bucket, key)
    except Exception as e:
        return Response(content=str(e), status_code=404)

    suffix = Path(filename).suffix.lower()
    media_type = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(
        suffix.lstrip("."), "image/png"
    )
    return Response(content=data, media_type=media_type)


@app.get("/api/marks")
def get_marks(
    bucket: Optional[str] = Query(default=None),
    prefix: Optional[str] = Query(default=None),
    subdir: Optional[str] = Query(default=None),
):
    """Get all marks (agree/disagree)."""
    bucket = bucket or DEFAULT_BUCKET
    prefix = prefix or DEFAULT_PREFIX
    subdir = subdir if subdir is not None else DEFAULT_SUBDIR
    subdir_part = f"{subdir}/" if subdir else ""
    key = f"{prefix}/marks/{subdir_part}marks.json"
    try:
        data = bos_read_json(bucket, key)
    except Exception:
        data = {}
    return data


@app.post("/api/mark/{case_id}")
def set_mark(
    case_id: str,
    mark: str = Query(..., description="agree or disagree or clear"),
    bucket: Optional[str] = Query(default=None),
    prefix: Optional[str] = Query(default=None),
    subdir: Optional[str] = Query(default=None),
):
    """Mark a case as agree/disagree."""
    bucket = bucket or DEFAULT_BUCKET
    prefix = prefix or DEFAULT_PREFIX
    subdir = subdir if subdir is not None else DEFAULT_SUBDIR
    subdir_part = f"{subdir}/" if subdir else ""
    key = f"{prefix}/marks/{subdir_part}marks.json"
    try:
        marks = bos_read_json(bucket, key)
    except Exception:
        marks = {}

    if mark == "clear":
        marks.pop(case_id, None)
    else:
        marks[case_id] = mark

    # Write back to BOS
    _bos_client.put_object_from_string(
        bucket, key, json.dumps(marks, ensure_ascii=False)
    )
    return {"ok": True, "case_id": case_id, "mark": mark}


@app.get("/api/stats")
def get_stats(
    bucket: Optional[str] = Query(default=None),
    prefix: Optional[str] = Query(default=None),
    subdir: Optional[str] = Query(default=None),
):
    """Get aggregate statistics (loaded independently from page data)."""
    bucket = bucket or DEFAULT_BUCKET
    prefix = prefix or DEFAULT_PREFIX
    subdir = subdir if subdir is not None else DEFAULT_SUBDIR
    case_ids = bos_list_case_ids(bucket, prefix, subdir)
    subdir_part = f"{subdir}/" if subdir else ""

    total = 0
    good = 0
    medium = 0
    bad = 0
    score_sum = 0

    for case_id in case_ids:
        try:
            score_data = bos_read_json(bucket, f"{prefix}/output/{subdir_part}{case_id}.json")
            total += 1
            grade = score_data.get("grade", "")
            if grade == "good":
                good += 1
            elif grade == "medium":
                medium += 1
            elif grade == "bad":
                bad += 1
            score_sum += score_data.get("score", 0)
        except Exception:
            continue

    avg_score = round(score_sum / total, 1) if total > 0 else 0

    # Read marks
    marks_key = f"{prefix}/marks/{subdir_part}marks.json"
    try:
        marks_data = bos_read_json(bucket, marks_key)
    except Exception:
        marks_data = {}

    agree = sum(1 for v in marks_data.values() if v == "agree")
    disagree = sum(1 for v in marks_data.values() if v == "disagree")

    return {
        "total": total,
        "good": good,
        "medium": medium,
        "bad": bad,
        "agree": agree,
        "disagree": disagree,
        "avg_score": avg_score,
    }


@app.get("/api/subdirs")
def list_subdirs(
    bucket: Optional[str] = Query(default=None),
    prefix: Optional[str] = Query(default=None),
):
    """List available score subdirectories."""
    bucket = bucket or DEFAULT_BUCKET
    prefix = prefix or DEFAULT_PREFIX
    subdirs = bos_list_subdirs(bucket, prefix)
    return {"subdirs": subdirs}


@app.get("/api/prefixes")
def list_prefixes(
    bucket: Optional[str] = Query(default=None),
    base_prefix: Optional[str] = Query(default=None),
):
    """List available render type prefixes (e.g., uv_check, rgb_closeup, normal_map)."""
    bucket = bucket or DEFAULT_BUCKET
    if base_prefix is None:
        # Extract base from DEFAULT_PREFIX: "robin_renders/rgb_closeup" -> "robin_renders/"
        parts = DEFAULT_PREFIX.split("/")
        base_prefix = parts[0] + "/" if parts else ""

    prefixes = []
    response = _bos_client.list_objects(
        bucket_name=bucket, prefix=base_prefix, delimiter="/", max_keys=1000
    )
    if hasattr(response, "common_prefixes") and response.common_prefixes:
        for cp in response.common_prefixes:
            name = cp.prefix[len(base_prefix):].rstrip("/")
            if name:
                prefixes.append(name)
    return {"bucket": bucket, "base_prefix": base_prefix, "prefixes": prefixes}


@app.get("/api/buckets")
def list_buckets():
    """List available BOS buckets."""
    try:
        response = _bos_client.list_buckets()
        buckets = [b.name for b in response.buckets] if hasattr(response, 'buckets') else []
        return {"buckets": buckets}
    except Exception as e:
        return {"buckets": [], "error": str(e)}


# ============================================================================
# Frontend HTML
# ============================================================================

@app.get("/", response_class=HTMLResponse)
def index(
    bucket: Optional[str] = Query(default=None),
    prefix: Optional[str] = Query(default=None),
    subdir: Optional[str] = Query(default=None),
):
    bucket = bucket or DEFAULT_BUCKET
    prefix = prefix or DEFAULT_PREFIX
    subdir = subdir if subdir is not None else DEFAULT_SUBDIR
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Score Viewer</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #eee; }}
.header {{ background: #16213e; padding: 12px 24px; display: flex; align-items: center; gap: 16px; position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 8px rgba(0,0,0,0.3); }}
.header h1 {{ font-size: 18px; color: #4fc3f7; }}
.controls {{ display: flex; gap: 8px; align-items: center; }}
.controls input, .controls select {{ padding: 6px 10px; border-radius: 4px; border: 1px solid #333; background: #0f3460; color: #eee; font-size: 13px; }}
.controls input {{ width: 220px; }}
.stats {{ margin-left: auto; font-size: 13px; color: #888; display: flex; gap: 16px; }}
.stats span {{ padding: 4px 8px; background: #0f3460; border-radius: 3px; }}
.stats-panel {{ background: #16213e; padding: 16px 24px; display: flex; gap: 24px; border-bottom: 1px solid #333; }}
.stats-item {{ flex: 1; text-align: center; }}
.stats-item .label {{ font-size: 11px; color: #888; text-transform: uppercase; }}
.stats-item .value {{ font-size: 24px; font-weight: bold; margin-top: 4px; }}
.grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; padding: 16px; }}
@media (max-width: 1600px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}
.card {{ background: #16213e; border-radius: 8px; overflow: hidden; border: 1px solid #333; transition: border-color 0.2s; }}
.card:hover {{ border-color: #4fc3f7; }}
.card-images {{ display: flex; flex-wrap: wrap; gap: 2px; background: #000; }}
.card-images img {{ flex: 1 1 calc(33.3% - 2px); min-width: 30%; height: auto; max-height: 280px; object-fit: contain; cursor: pointer; background: #111; }}
.card-body {{ padding: 12px; }}
.card-id {{ font-size: 10px; color: #888; word-break: break-all; margin-bottom: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.card-score {{ font-size: 20px; font-weight: bold; }}
.card-meta {{ font-size: 11px; color: #aaa; margin-top: 4px; }}
.grade {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: bold; text-transform: uppercase; }}
.grade-good {{ background: #1b5e20; color: #a5d6a7; }}
.grade-medium {{ background: #e65100; color: #ffcc80; }}
.grade-bad {{ background: #b71c1c; color: #ef9a9a; }}
.issues {{ font-size: 10px; color: #ef9a9a; margin-top: 4px; max-height: 32px; overflow: hidden; }}
.nav {{ display: flex; gap: 8px; padding: 16px; justify-content: center; position: sticky; bottom: 0; background: #1a1a2e; }}
.nav button {{ padding: 8px 16px; background: #0f3460; color: #eee; border: 1px solid #333; border-radius: 4px; cursor: pointer; }}
.nav button:hover {{ background: #4fc3f7; color: #000; }}
.modal {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); z-index: 200; justify-content: center; align-items: center; }}
.modal.active {{ display: flex; }}
.modal img {{ max-width: 90%; max-height: 90%; object-fit: contain; }}
.loading {{ text-align: center; padding: 40px; color: #888; }}
</style>
</style>
</head>
<body>
<div class="header">
    <h1>Score Viewer</h1>
    <div class="controls">
        <select id="bucket-switch" title="Bucket"></select>
        <select id="prefix-switch" title="Render Type"></select>
        <select id="subdir-switch" title="Score Task"></select>
        <input id="search" type="text" placeholder="Search case ID...">
        <select id="grade-filter">
            <option value="">All grades</option>
            <option value="good">Good</option>
            <option value="medium">Medium</option>
            <option value="bad">Bad</option>
        </select>
        <input id="score-min" type="number" min="0" max="100" placeholder="Min" style="width:60px; padding:4px; background:#0f3460; color:#eee; border:1px solid #333; border-radius:3px; text-align:center;" title="Min Score">
        <input id="score-max" type="number" min="0" max="100" placeholder="Max" style="width:60px; padding:4px; background:#0f3460; color:#eee; border:1px solid #333; border-radius:3px; text-align:center;" title="Max Score">
        <select id="mark-filter">
            <option value="">All marks</option>
            <option value="agree">✓ Agree</option>
            <option value="disagree">✗ Disagree</option>
            <option value="unmarked">Unmarked</option>
        </select>
    </div>
    <div class="stats" id="stats"></div>
</div>
<div class="stats-panel" id="stats-panel">
    <div class="stats-item">
        <div class="label">Total</div>
        <div class="value" id="stat-total">-</div>
    </div>
    <div class="stats-item">
        <div class="label">Good</div>
        <div class="value" style="color:#a5d6a7;" id="stat-good">-</div>
    </div>
    <div class="stats-item">
        <div class="label">Medium</div>
        <div class="value" style="color:#ffcc80;" id="stat-medium">-</div>
    </div>
    <div class="stats-item">
        <div class="label">Bad</div>
        <div class="value" style="color:#ef9a9a;" id="stat-bad">-</div>
    </div>
    <div class="stats-item">
        <div class="label">Agree</div>
        <div class="value" style="color:#a5d6a7;" id="stat-agree">-</div>
    </div>
    <div class="stats-item">
        <div class="label">Disagree</div>
        <div class="value" style="color:#ef9a9a;" id="stat-disagree">-</div>
    </div>
    <div class="stats-item">
        <div class="label">Avg Score</div>
        <div class="value" style="color:#4fc3f7;" id="stat-avg">-</div>
    </div>
</div>
<div class="grid" id="grid">
    <div class="loading">Loading cases...</div>
</div>
<div class="nav">
    <button onclick="prevPage()">← Prev</button>
    <input id="page-jump" type="number" min="1" style="width:60px; padding:4px; background:#0f3460; color:#eee; border:1px solid #333; border-radius:3px; text-align:center;" placeholder="Page">
    <button onclick="jumpToPage()">Go</button>
    <span id="page-info" style="padding:8px; color:#888;"></span>
    <button onclick="nextPage()">Next →</button>
</div>
<div class="modal" id="modal" onclick="closeModal()">
    <img id="modal-img">
</div>

<script>
const BUCKET = "{bucket}";
const PREFIX = "{prefix}";
const SUBDIR = "{subdir}";
const PAGE_SIZE = 20;
let allCases = [];
let totalCases = 0;
let totalPages = 1;
let marks = {{}};
let page = 0;
let searchTimeout = null;

function formatSubScores(c) {{
    const excludeKeys = ['score', 'grade', 'issues', 'case_id', 'images'];
    const parts = [];
    for (const [key, val] of Object.entries(c)) {{
        if (excludeKeys.includes(key)) continue;
        if (key.endsWith('_score')) {{
            // Score fields: show as "key: value"
            const label = key.replace('_score', '');
            parts.push(`${{label}}: ${{val || 0}}`);
        }} else {{
            // Metadata fields: show as "value" only
            if (val) parts.push(String(val));
        }}
    }}
    return parts.join(' | ');
}}

async function loadMarks() {{
    try {{
        const resp = await fetch(`/api/marks?bucket=${{BUCKET}}&prefix=${{PREFIX}}&subdir=${{SUBDIR}}`);
        marks = await resp.json();
    }} catch(e) {{
        marks = {{}};
    }}
}}

async function loadStats() {{
    try {{
        const resp = await fetch(`/api/stats?bucket=${{BUCKET}}&prefix=${{PREFIX}}&subdir=${{SUBDIR}}`);
        const s = await resp.json();
        document.getElementById('stat-total').textContent = s.total;
        document.getElementById('stat-good').textContent = s.good;
        document.getElementById('stat-medium').textContent = s.medium;
        document.getElementById('stat-bad').textContent = s.bad;
        document.getElementById('stat-agree').textContent = s.agree;
        document.getElementById('stat-disagree').textContent = s.disagree;
        document.getElementById('stat-avg').textContent = s.avg_score;
    }} catch(e) {{
        // Stats loading failed silently
    }}
}}

async function setMark(caseId, mark) {{
    const url = `/api/mark/${{caseId}}?mark=${{mark}}&bucket=${{BUCKET}}&prefix=${{PREFIX}}&subdir=${{SUBDIR}}`;
    await fetch(url, {{method: 'POST'}});
    marks[caseId] = mark === 'clear' ? undefined : mark;
    if (mark === 'clear') delete marks[caseId];
    renderPage();
}}

async function loadCases() {{
    const grade = document.getElementById('grade-filter').value;
    const search = document.getElementById('search').value;
    const markFilter = document.getElementById('mark-filter').value;
    const scoreMin = document.getElementById('score-min').value;
    const scoreMax = document.getElementById('score-max').value;
    let url = `/api/cases?bucket=${{BUCKET}}&prefix=${{PREFIX}}&subdir=${{SUBDIR}}&page=${{page}}&page_size=${{PAGE_SIZE}}`;
    if (grade) url += `&grade=${{grade}}`;
    if (search) url += `&search=${{encodeURIComponent(search)}}`;
    if (scoreMin) url += `&score_min=${{scoreMin}}`;
    if (scoreMax) url += `&score_max=${{scoreMax}}`;
    if (markFilter) url += `&mark=${{markFilter}}`;

    document.getElementById('grid').innerHTML = '<div class="loading">Loading...</div>';
    const resp = await fetch(url);
    const data = await resp.json();

    allCases = data.cases;
    totalCases = data.total;
    totalPages = Math.ceil(data.total / PAGE_SIZE);

    document.getElementById('stats').textContent = `${{data.total}} cases`;
    document.getElementById('page-info').textContent = `${{page + 1}} / ${{totalPages}}`;
    renderPage();
}}

function renderPage() {{
    if (!allCases.length) {{
        document.getElementById('grid').innerHTML = '<div class="loading">No results</div>';
        return;
    }}

    document.getElementById('grid').innerHTML = allCases.map(c => {{
        const gradeClass = 'grade-' + (c.grade || 'unknown');
        const issues = (c.issues || []).join(', ');
        const caseId = c.case_id;
        const images = (c.images || []).filter(f => f.endsWith('.png') || f.endsWith('.jpg') || f.endsWith('.webp'));
        const imgsHtml = images.map(f => `<img src="/api/image/${{caseId}}/${{f}}?bucket=${{BUCKET}}&prefix=${{PREFIX}}&subdir=${{SUBDIR}}" onerror="this.style.display='none'" onclick="openModal(this.src)">`).join('');

        const mark = marks[caseId];
        const markBtns = `
            <div style="margin-top:8px; display:flex; gap:4px;">
                <button onclick="setMark('${{caseId}}','agree')" style="flex:1; padding:4px; background:${{mark==='agree'?'#1b5e20':'#333'}}; color:#eee; border:1px solid #555; border-radius:3px; cursor:pointer; font-size:11px;">✓ Agree</button>
                <button onclick="setMark('${{caseId}}','disagree')" style="flex:1; padding:4px; background:${{mark==='disagree'?'#b71c1c':'#333'}}; color:#eee; border:1px solid #555; border-radius:3px; cursor:pointer; font-size:11px;">✗ Disagree</button>
                ${{mark ? `<button onclick="setMark('${{caseId}}','clear')" style="padding:4px 8px; background:#555; color:#eee; border:1px solid #777; border-radius:3px; cursor:pointer; font-size:11px;">Clear</button>` : ''}}
            </div>
        `;

        return `<div class="card">
            <div class="card-images">${{imgsHtml}}</div>
            <div class="card-body">
                <div class="card-id">${{caseId}}</div>
                <div class="card-score">${{c.score || 0}}<span style="font-size:14px;color:#888">/100</span>
                    <span class="grade ${{gradeClass}}">${{c.grade || '?'}}</span>
                </div>
                <div class="card-meta">${{formatSubScores(c)}}</div>
                ${{issues ? `<div class="issues">${{issues}}</div>` : ''}}
                ${{markBtns}}
            </div>
        </div>`;
    }}).join('');
}}

function nextPage() {{ if (page < totalPages - 1) {{ page++; loadCases(); window.scrollTo(0,0); }} }}
function prevPage() {{ if (page > 0) {{ page--; loadCases(); window.scrollTo(0,0); }} }}
function jumpToPage() {{
    const input = document.getElementById('page-jump');
    let target = parseInt(input.value);
    if (isNaN(target) || target < 1) target = 1;
    if (target > totalPages) target = totalPages;
    page = target - 1;
    input.value = '';
    loadCases();
    window.scrollTo(0,0);
}}
function openModal(src) {{ document.getElementById('modal').classList.add('active'); document.getElementById('modal-img').src = src; }}
function closeModal() {{ document.getElementById('modal').classList.remove('active'); }}

async function loadBuckets() {{
    try {{
        const resp = await fetch('/api/buckets');
        const data = await resp.json();
        const select = document.getElementById('bucket-switch');
        select.innerHTML = data.buckets.map(b => `<option value="${{b}}" ${{b === BUCKET ? 'selected' : ''}}>${{b}}</option>`).join('');
    }} catch(e) {{
        document.getElementById('bucket-switch').innerHTML = `<option value="${{BUCKET}}" selected>${{BUCKET}}</option>`;
    }}
}}

async function loadPrefixes() {{
    const bucket = document.getElementById('bucket-switch').value || BUCKET;
    const basePrefix = PREFIX.split('/')[0] + '/';
    const resp = await fetch(`/api/prefixes?bucket=${{bucket}}&base_prefix=${{encodeURIComponent(basePrefix)}}`);
    const data = await resp.json();
    const select = document.getElementById('prefix-switch');
    const currentType = PREFIX.split('/').slice(1).join('/');
    select.innerHTML = data.prefixes.map(p => `<option value="${{p}}" ${{p === currentType ? 'selected' : ''}}>${{p}}</option>`).join('');
}}

async function loadSubdirs() {{
    const bucket = document.getElementById('bucket-switch').value || BUCKET;
    const basePrefix = PREFIX.split('/')[0];
    const renderType = document.getElementById('prefix-switch').value || PREFIX.split('/').slice(1).join('/');
    const fullPrefix = basePrefix + '/' + renderType;
    const resp = await fetch(`/api/subdirs?bucket=${{bucket}}&prefix=${{encodeURIComponent(fullPrefix)}}`);
    const data = await resp.json();
    const select = document.getElementById('subdir-switch');
    select.innerHTML = `<option value="">(root)</option>` + data.subdirs.map(s => `<option value="${{s}}" ${{s === SUBDIR ? 'selected' : ''}}>${{s}}</option>`).join('');
}}

function switchView() {{
    const bucket = document.getElementById('bucket-switch').value;
    const basePrefix = PREFIX.split('/')[0];
    const renderType = document.getElementById('prefix-switch').value;
    const subdir = document.getElementById('subdir-switch').value;
    const fullPrefix = basePrefix + '/' + renderType;
    window.location.href = `/?bucket=${{encodeURIComponent(bucket)}}&prefix=${{encodeURIComponent(fullPrefix)}}&subdir=${{encodeURIComponent(subdir)}}`;
}}

document.getElementById('bucket-switch').addEventListener('change', async () => {{
    await loadPrefixes();
    await loadSubdirs();
    switchView();
}});
document.getElementById('prefix-switch').addEventListener('change', async () => {{
    await loadSubdirs();
    switchView();
}});
document.getElementById('subdir-switch').addEventListener('change', () => {{ switchView(); }});

document.getElementById('search').addEventListener('input', () => {{
    clearTimeout(searchTimeout);
    page = 0;
    searchTimeout = setTimeout(loadCases, 300);
}});
document.getElementById('grade-filter').addEventListener('change', () => {{ page = 0; loadCases(); }});
document.getElementById('mark-filter').addEventListener('change', () => {{ page = 0; loadCases(); }});
document.getElementById('score-min').addEventListener('change', () => {{ page = 0; loadCases(); }});
document.getElementById('score-max').addEventListener('change', () => {{ page = 0; loadCases(); }});
document.getElementById('page-jump').addEventListener('keydown', e => {{
    if (e.key === 'Enter') {{ e.preventDefault(); jumpToPage(); }}
}});
document.addEventListener('keydown', e => {{
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    if (e.key === 'Escape') closeModal();
    if (e.key === 'ArrowLeft') prevPage();
    if (e.key === 'ArrowRight') nextPage();
}});

(async () => {{
    await loadBuckets();
    await loadPrefixes();
    await loadSubdirs();
    await loadMarks();
    loadCases();
    loadStats();
}})();
</script>
</body>
</html>"""


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Score Viewer Web UI")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET, help="BOS bucket")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="Storage prefix")
    parser.add_argument("--subdir", default=DEFAULT_SUBDIR, help="Output subdir (e.g. 细节丰富度)")
    parser.add_argument("--port", type=int, default=8765, help="Port")
    parser.add_argument("--host", default="127.0.0.1", help="Host")
    args = parser.parse_args()

    DEFAULT_BUCKET = args.bucket
    DEFAULT_PREFIX = args.prefix

    # Auto-detect subdir if not specified
    if args.subdir:
        DEFAULT_SUBDIR = args.subdir
    else:
        subdirs = bos_list_subdirs(DEFAULT_BUCKET, DEFAULT_PREFIX)
        if not subdirs:
            DEFAULT_SUBDIR = ""
        elif len(subdirs) == 1:
            DEFAULT_SUBDIR = subdirs[0]
            print(f"Auto-selected subdir: {DEFAULT_SUBDIR}")
        else:
            print("\nAvailable score subdirs:")
            for i, s in enumerate(subdirs):
                print(f"  [{i}] {s}")
            print(f"  [{len(subdirs)}] (all)")
            while True:
                try:
                    choice = input(f"Select subdir [0-{len(subdirs)}]: ").strip()
                    idx = int(choice)
                    if idx == len(subdirs):
                        DEFAULT_SUBDIR = ""
                        break
                    elif 0 <= idx < len(subdirs):
                        DEFAULT_SUBDIR = subdirs[idx]
                        break
                except (ValueError, IndexError):
                    pass

    print(f"\nScore Viewer: http://{args.host}:{args.port}")
    print(f"BOS: {args.bucket}/{args.prefix}" + (f"/{DEFAULT_SUBDIR}" if DEFAULT_SUBDIR else "") + "\n")
    uvicorn.run(app, host=args.host, port=args.port)
