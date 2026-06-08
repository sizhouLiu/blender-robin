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


(bucket: str, prefix: str, subdir: str = "") -> list:
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
# API Routes
# ============================================================================

@app.get("/api/cases")
def list_cases(
    bucket: str = Query(default=DEFAULT_BUCKET),
    prefix: str = Query(default=DEFAULT_PREFIX),
    subdir: str = Query(default=DEFAULT_SUBDIR),
    grade: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
):
    """List all scored cases with optional filtering."""
    case_ids = bos_list_case_ids(bucket, prefix, subdir)
    subdir_part = f"{subdir}/" if subdir else ""

    results = []
    for case_id in case_ids:
        if search and search.lower() not in case_id.lower():
            continue
        try:
            score_data = bos_read_json(bucket, f"{prefix}/output/{subdir_part}{case_id}.json")
        except Exception:
            continue
        if grade and score_data.get("grade") != grade:
            continue
        images = [Path(k).name for k in bos_list_images(bucket, prefix, case_id)]
        results.append({"case_id": case_id, "images": images, **score_data})

    return {"total": len(results), "cases": results}


@app.get("/api/case/{case_id}")
def get_case(
    case_id: str,
    bucket: str = Query(default=DEFAULT_BUCKET),
    prefix: str = Query(default=DEFAULT_PREFIX),
    subdir: str = Query(default=DEFAULT_SUBDIR),
):
    """Get score and image list for a single case."""
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
    bucket: str = Query(default=DEFAULT_BUCKET),
    prefix: str = Query(default=DEFAULT_PREFIX),
):
    """Proxy an image from BOS."""
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
    bucket: str = Query(default=DEFAULT_BUCKET),
    prefix: str = Query(default=DEFAULT_PREFIX),
    subdir: str = Query(default=DEFAULT_SUBDIR),
):
    """Get all marks (agree/disagree)."""
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
    bucket: str = Query(default=DEFAULT_BUCKET),
    prefix: str = Query(default=DEFAULT_PREFIX),
    subdir: str = Query(default=DEFAULT_SUBDIR),
):
    """Mark a case as agree/disagree."""
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


# ============================================================================
# Frontend HTML
# ============================================================================

@app.get("/", response_class=HTMLResponse)
def index(
    bucket: str = Query(default=DEFAULT_BUCKET),
    prefix: str = Query(default=DEFAULT_PREFIX),
    subdir: str = Query(default=DEFAULT_SUBDIR),
):
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
        <input id="search" type="text" placeholder="Search case ID...">
        <select id="grade-filter">
            <option value="">All grades</option>
            <option value="good">Good</option>
            <option value="medium">Medium</option>
            <option value="bad">Bad</option>
        </select>
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
let marks = {{}};
let page = 0;
let searchTimeout = null;

async function loadMarks() {{
    try {{
        const resp = await fetch(`/api/marks?bucket=${{BUCKET}}&prefix=${{PREFIX}}&subdir=${{SUBDIR}}`);
        marks = await resp.json();
    }} catch(e) {{
        marks = {{}};
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
    let url = `/api/cases?bucket=${{BUCKET}}&prefix=${{PREFIX}}&subdir=${{SUBDIR}}`;
    if (grade) url += `&grade=${{grade}}`;
    if (search) url += `&search=${{encodeURIComponent(search)}}`;

    document.getElementById('grid').innerHTML = '<div class="loading">Loading...</div>';
    const resp = await fetch(url);
    const data = await resp.json();

    // Apply mark filter
    if (markFilter === 'agree') {{
        allCases = data.cases.filter(c => marks[c.case_id] === 'agree');
    }} else if (markFilter === 'disagree') {{
        allCases = data.cases.filter(c => marks[c.case_id] === 'disagree');
    }} else if (markFilter === 'unmarked') {{
        allCases = data.cases.filter(c => !marks[c.case_id]);
    }} else {{
        allCases = data.cases;
    }}

    // Update statistics
    updateStats(allCases);

    document.getElementById('stats').textContent = `${{allCases.length}} / ${{data.total}} cases`;
    page = 0;
    renderPage();
}}

function updateStats(cases) {{
    const total = cases.length;
    const good = cases.filter(c => c.grade === 'good').length;
    const medium = cases.filter(c => c.grade === 'medium').length;
    const bad = cases.filter(c => c.grade === 'bad').length;
    const agree = cases.filter(c => marks[c.case_id] === 'agree').length;
    const disagree = cases.filter(c => marks[c.case_id] === 'disagree').length;
    const avgScore = total > 0 ? (cases.reduce((sum, c) => sum + (c.score || 0), 0) / total).toFixed(1) : 0;

    document.getElementById('stat-total').textContent = total;
    document.getElementById('stat-good').textContent = good;
    document.getElementById('stat-medium').textContent = medium;
    document.getElementById('stat-bad').textContent = bad;
    document.getElementById('stat-agree').textContent = agree;
    document.getElementById('stat-disagree').textContent = disagree;
    document.getElementById('stat-avg').textContent = avgScore;
}}

function renderPage() {{
    const start = page * PAGE_SIZE;
    const end = start + PAGE_SIZE;
    const slice = allCases.slice(start, end);
    const totalPages = Math.ceil(allCases.length / PAGE_SIZE);

    document.getElementById('page-info').textContent = `${{page + 1}} / ${{totalPages}}`;

    if (!slice.length) {{
        document.getElementById('grid').innerHTML = '<div class="loading">No results</div>';
        return;
    }}

    document.getElementById('grid').innerHTML = slice.map(c => {{
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
                <div class="card-meta">info: ${{c.info_score || 0}}/60 | layer: ${{c.layer_score || 0}}/40 | ${{c.style || ''}} | ${{c.asset_type || ''}}</div>
                ${{issues ? `<div class="issues">${{issues}}</div>` : ''}}
                ${{markBtns}}
            </div>
        </div>`;
    }}).join('');
}}

function nextPage() {{ if ((page + 1) * PAGE_SIZE < allCases.length) {{ page++; renderPage(); window.scrollTo(0,0); }} }}
function prevPage() {{ if (page > 0) {{ page--; renderPage(); window.scrollTo(0,0); }} }}
function openModal(src) {{ document.getElementById('modal').classList.add('active'); document.getElementById('modal-img').src = src; }}
function closeModal() {{ document.getElementById('modal').classList.remove('active'); }}

document.getElementById('search').addEventListener('input', () => {{
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(loadCases, 300);
}});
document.getElementById('grade-filter').addEventListener('change', loadCases);
document.getElementById('mark-filter').addEventListener('change', loadCases);
document.addEventListener('keydown', e => {{
    if (e.key === 'Escape') closeModal();
    if (e.key === 'ArrowLeft') prevPage();
    if (e.key === 'ArrowRight') nextPage();
}});

(async () => {{
    await loadMarks();
    loadCases();
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
