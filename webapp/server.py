"""Bevell 3D web app: upload photos taken on the capture sheet, watch the scan, take the CAD.

    set -a; source path/to/meta.env; set +a
    .venv/bin/uvicorn webapp.server:app --port 8300

Scans live under out/scans/<id>/: the uploads, every pipeline output, and status.json,
which the page polls. One scan runs at a time per process; a second waits its turn.
"""
import json, os, re, shutil, threading, time, traceback, uuid
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCANS = os.environ.get("BEVELL3D_SCANS", os.path.join(ROOT, "out", "scans"))
SHEET = os.path.join(ROOT, "assets", "bevell_capture_sheet.pdf")
STAGES = ["plan", "photos", "markers", "masks", "hull", "revolve", "sam3d", "fit", "cad", "done"]
FILES = {  # name -> (label, media type)
    "model.step": ("Model, STEP", "application/step"),
    "model.stl": ("Model as scanned, STL", "model/stl"),
    "model_cad.stl": ("Model from the CAD, STL", "model/stl"),
    "model_fusion.zip": ("Fusion 360 script: the CAD as sketches and extrusions", "application/zip"),
    "model_tree.json": ("The CAD's feature tree, JSON", "application/json"),
    "holder.step": ("Holder, STEP", "application/step"),
    "holder.stl": ("Holder, STL", "model/stl"),
    "holder.3mf": ("Holder, 3MF", "model/3mf"),
    "holder_top.dxf": ("Holder outline, DXF", "image/vnd.dxf"),
    "holder_nest.stl": ("Holder that follows the underside, STL", "model/stl"),
    "pads.3mf": ("Gripper pads for the SO-101, 3MF", "model/3mf"),
    "pad_fixed_jaw.stl": ("Gripper pad, fixed jaw, STL", "model/stl"),
    "pad_moving_jaw.stl": ("Gripper pad, moving jaw, STL", "model/stl"),
    "grasp.json": ("Where to grasp it, JSON", "application/json"),
    "fixture.3mf": ("Robot fixture, 3MF", "model/3mf"),
    "fixture.step": ("Robot fixture, STEP", "application/step"),
    "fixture.stl": ("Robot fixture, STL", "model/stl"),
    "fixture.json": ("Robot fixture: the pick in the tag's frame, JSON", "application/json"),
    "tag.pdf": ("Robot fixture tag, PDF to print at 100%", "application/pdf"),
    "scissor_jaws.3mf": ("Custom SO-101 grippers for these scissors (both parts), 3MF", "model/3mf"),
    "scissor_moving_jaw.stl": ("Custom SO-101 moving jaw, STL", "model/stl"),
    "scissor_wrist_roll_follower.stl": ("Custom SO-101 wrist-roll follower (fixed jaw), STL", "model/stl"),
    "scissor_jaws.json": ("Custom grippers: plugs, holes and the simulation, JSON", "application/json"),
    "scissor_jaws_preview.stl": ("Custom grippers on the SO-101, preview STL", "model/stl"),
    "scissor_jaws_scissors.stl": ("The scissors in the custom grippers, preview STL", "model/stl"),
    "scissor_jaws_sim.xml": ("The MuJoCo model of the custom grippers working the scissors", "application/xml"),
    "tool_fingers.3mf": ("Custom robot grippers for this tool (stick-on), 3MF", "model/3mf"),
    "tool_fingers.stl": ("Custom robot grippers for this tool (stick-on), STL", "model/stl"),
    "tool_fingers.step": ("Custom robot grippers for this tool (stick-on), STEP", "model/step"),
    "tool_fingers.json": ("Custom robot grippers (stick-on): jaw gap and how to fit them, JSON", "application/json"),
    "tool_fingers_on_tool.stl": ("Custom robot grippers (stick-on) placed on the tool, STL", "model/stl"),
    "agent_model.step": ("Editable CAD by Muse Spark, STEP", "application/step"),
    "agent_fusion.zip": ("Fusion 360 script: the feature tree as a timeline", "application/zip"),
    "agent_tree.json": ("Feature tree, JSON", "application/json"),
    "agent_model.py": ("Editable CAD by Muse Spark, CadQuery script", "text/x-python"),
    "agent_model.stl": ("Editable CAD by Muse Spark, STL", "model/stl"),
}
MIN_PHOTOS, MAX_PHOTOS = 8, 40
ID = re.compile(r"^[a-z0-9-]{4,64}$")
# Deployed, a scan or a CAD agent run needs the passcode and counts against a daily cap, so the
# Meta and Modal credits cannot be run down. Both are off unless set (the local app stays open).
PASSCODE = os.environ.get("BEVELL3D_PASSCODE", "")
DAILY_CAP = int(os.environ.get("BEVELL3D_DAILY_CAP", "0") or 0)
usage_lock = threading.Lock()


def _check_access(request):
    import hmac
    if PASSCODE and not hmac.compare_digest(request.headers.get("x-passcode", "").strip().lower(), PASSCODE.lower()):
        raise HTTPException(401, "That passcode isn't right.")


def _count_run():
    """Count one run against today's cap (UTC); refuse when it is used up."""
    if not DAILY_CAP:
        return
    path = os.path.join(SCANS, "_usage.json")
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with usage_lock:
        use = json.load(open(path)) if os.path.exists(path) else {}
        if use.get(today, 0) >= DAILY_CAP:
            raise HTTPException(429, f"Today's {DAILY_CAP} runs are used up. Try again tomorrow, or see the examples.")
        use = {today: use.get(today, 0) + 1}
        os.makedirs(SCANS, exist_ok=True)
        json.dump(use, open(path + ".tmp", "w")); os.replace(path + ".tmp", path)

app = FastAPI(title="Bevell 3D")
lock = threading.Lock()


def _status(scan_id, **kw):
    path = os.path.join(SCANS, scan_id, "status.json")
    st = json.load(open(path)) if os.path.exists(path) else {}
    st.update(kw, updated=time.time())
    json.dump(st, open(path + ".tmp", "w"), default=float)
    os.replace(path + ".tmp", path)
    return st


SCAN_TIMEOUT_S = int(os.environ.get("BEVELL3D_SCAN_TIMEOUT", "1200"))
AGENT_TIMEOUT_S = int(os.environ.get("BEVELL3D_AGENT_TIMEOUT", "1800"))


def friendly(e):
    """What the person sees. Our own refusals (ValueError) are written for people; anything else
    is ours to fix, so it says so, and the detail stays in the status file."""
    if isinstance(e, ValueError) and str(e):
        return str(e)
    return "Something went wrong on our side. Try again; if it happens again, tell us."


def _scan_child(scan_id, paths, scans_dir):
    """The pipeline in a process of its own (spawned), writing its progress to status.json."""
    global SCANS
    SCANS = scans_dir
    from bevell3d.run import run
    started = time.time()
    done = []

    def progress(stage, detail=""):
        st = json.load(open(os.path.join(SCANS, scan_id, "status.json")))
        if st.get("stage") and st["stage"] not in done:
            done.append(st["stage"])
        _status(scan_id, stage=stage, detail=detail, done=done, elapsed=round(time.time() - started, 1))

    try:
        tool = json.load(open(os.path.join(SCANS, scan_id, "status.json"))).get("mode") == "gripper"
        summary = run(paths, os.path.join(SCANS, scan_id, "result"), log=lambda *a: None, progress=progress, tool=tool)
        _status(scan_id, state="done", stage="done", elapsed=round(time.time() - started, 1), summary=summary)
    except Exception as e:
        traceback.print_exc()
        _status(scan_id, state="failed", error=friendly(e), error_detail=f"{type(e).__name__}: {e}"[:500],
                elapsed=round(time.time() - started, 1))


def _agent_child(scan_id, scans_dir):
    global SCANS
    SCANS = scans_dir
    from bevell3d.agent_cad import run_agent
    res = os.path.join(SCANS, scan_id, "result")
    started = time.time()

    def log(msg):
        _status(scan_id, agent={"state": "running", "detail": str(msg)[:160], "elapsed": round(time.time() - started)})

    log("Muse Spark is writing the CAD")
    try:
        rep = run_agent(res, rounds=2, log=log)
        _status(scan_id, agent={"state": "done", "report": rep, "elapsed": round(time.time() - started)})
    except Exception as e:
        traceback.print_exc()
        _status(scan_id, agent={"state": "failed", "error": friendly(e), "error_detail": f"{type(e).__name__}: {e}"[:500]})


def _in_child(target, args, timeout, on_stop):
    """Run `target` in a spawned process and wait at most `timeout` s. A scan that hangs or
    crashes in native code then ends only itself: before, one stuck scan held the lock and every
    scan after it waited for ever, and a crash would have taken the server down."""
    import multiprocessing as mp
    # Not a daemon: the scan starts processes of its own (the holder's, the agent's builder),
    # which a daemonic process may not, and every holder failed with an AssertionError.
    p = mp.get_context("spawn").Process(target=target, args=args, daemon=False)
    p.start(); p.join(timeout)
    if p.is_alive():
        p.terminate(); p.join(10)
        if p.is_alive():
            p.kill(); p.join(5)
        on_stop("timeout")
    elif p.exitcode != 0:
        on_stop(f"exit {p.exitcode}")


def _work(scan_id, paths, target=None, timeout=None):
    started = time.time()
    with lock:                                   # one scan at a time per container
        _status(scan_id, state="running", stage="plan", detail="starting", started=started)

        def stopped(why):
            st = json.load(open(os.path.join(SCANS, scan_id, "status.json")))
            if st.get("state") in ("done", "failed"):
                return
            _status(scan_id, state="failed", error_detail=why, elapsed=round(time.time() - started, 1),
                    error="That scan took too long, so it was stopped. Try again with sharp photos of one object; "
                          "if it happens again, tell us." if why == "timeout" else
                          "The scan stopped unexpectedly. Try again; if it happens again, tell us.")
        _in_child(target or _scan_child, (scan_id, paths, SCANS), timeout or SCAN_TIMEOUT_S, stopped)


@app.get("/api/config")
def config():
    return {"passcode": bool(PASSCODE), "daily_cap": DAILY_CAP}


@app.post("/api/scans")
async def create_scan(request: Request, photos: list[UploadFile] = File(...), mode: str = Form("scan")):
    _check_access(request)
    if not (MIN_PHOTOS <= len(photos) <= MAX_PHOTOS):
        raise HTTPException(400, f"Upload {MIN_PHOTOS} to {MAX_PHOTOS} photos; you sent {len(photos)}.")
    _count_run()
    scan_id = uuid.uuid4().hex[:12]
    up = os.path.join(SCANS, scan_id, "upload")
    os.makedirs(up)
    paths = []
    for k, f in enumerate(photos):
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".heic", ".heif"):
            raise HTTPException(400, f"{f.filename}: send JPEG, PNG or HEIC photos.")
        p = os.path.join(up, f"IMG_{k:02d}{ext}")
        with open(p, "wb") as out:
            shutil.copyfileobj(f.file, out)
        paths.append(p)
    _status(scan_id, state="queued", stage="queued", photos=len(paths), created=time.time(), mode="gripper" if mode == "gripper" else "scan")
    threading.Thread(target=_work, args=(scan_id, paths), daemon=True).start()
    return {"id": scan_id}


@app.get("/api/scans/{scan_id}")
def scan_status(scan_id: str, request: Request):
    if not ID.match(scan_id) or not os.path.exists(os.path.join(SCANS, scan_id, "status.json")):
        raise HTTPException(404, "No scan with that id.")
    st = json.load(open(os.path.join(SCANS, scan_id, "status.json")))
    res = os.path.join(SCANS, scan_id, "result")
    if "plan" not in st and os.path.exists(os.path.join(res, "plan.json")):
        st["plan"] = json.load(open(os.path.join(res, "plan.json")))
    base = str(request.base_url).rstrip("/")
    st["files"] = [{"name": n, "label": l, "url": f"{base}/api/scans/{scan_id}/files/{n}"}
                   for n, (l, _) in FILES.items() if os.path.exists(os.path.join(res, n))]
    return JSONResponse(st)


@app.get("/api/scans/{scan_id}/files/{name}")
def scan_file(scan_id: str, name: str):
    if not ID.match(scan_id) or name not in FILES:
        raise HTTPException(404, "No such file.")
    p = os.path.join(SCANS, scan_id, "result", name)
    if not os.path.exists(p):
        raise HTTPException(404, "Not made yet.")
    return FileResponse(p, media_type=FILES[name][1], filename=f"bevell-{scan_id}-{name}")


def _agent(scan_id):
    with lock:
        def stopped(why):
            st = json.load(open(os.path.join(SCANS, scan_id, "status.json")))
            if (st.get("agent") or {}).get("state") in ("done", "failed"):
                return
            _status(scan_id, agent={"state": "failed", "error_detail": why,
                                    "error": "Writing the CAD took too long, so it was stopped. Try again." if why == "timeout"
                                    else "Writing the CAD stopped unexpectedly. Try again."})
        _in_child(_agent_child, (scan_id, SCANS), AGENT_TIMEOUT_S, stopped)


@app.post("/api/scans/{scan_id}/agent")
def start_agent(scan_id: str, request: Request):
    """Muse Spark writes the object as an editable CAD program; the photos tune and check it."""
    _check_access(request)
    res = os.path.join(SCANS, scan_id, "result")
    if not ID.match(scan_id) or not os.path.exists(os.path.join(res, "views.pkl")):
        raise HTTPException(404, "That scan has no photos to check CAD against.")
    _count_run()
    _status(scan_id, agent={"state": "queued", "detail": "starting"})
    threading.Thread(target=_agent, args=(scan_id,), daemon=True).start()
    return {"ok": True}


@app.get("/api/examples")
def examples():
    out = []
    for d in sorted(os.listdir(SCANS)) if os.path.isdir(SCANS) else []:
        if d.startswith("example-") and os.path.exists(os.path.join(SCANS, d, "status.json")):
            st = json.load(open(os.path.join(SCANS, d, "status.json")))
            out.append({"id": d, "name": st.get("title", d)})
    return out


@app.get("/sheet.pdf")
def sheet():
    return FileResponse(SHEET, media_type="application/pdf", filename="bevell-capture-sheet.pdf")


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
