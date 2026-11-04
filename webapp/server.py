"""Bevell 3D web app: upload photos taken on the capture sheet, watch the scan, take the CAD.

    set -a; source path/to/meta.env; set +a
    .venv/bin/uvicorn webapp.server:app --port 8300

Scans live under out/scans/<id>/: the uploads, every pipeline output, and status.json,
which the page polls. One scan runs at a time per process; a second waits its turn.
"""
import hashlib, hmac, json, os, re, shutil, sys, threading, time, traceback, uuid
from urllib.parse import quote
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, Form
from fastapi.concurrency import run_in_threadpool
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
    "custom_jaws.3mf": ("Custom SO-101 grippers for these scissors (both parts), 3MF", "model/3mf"),
    "custom_moving_jaw.stl": ("Custom SO-101 moving jaw, STL", "model/stl"),
    "custom_wrist_roll_follower.stl": ("Custom SO-101 wrist-roll follower (fixed jaw), STL", "model/stl"),
    "custom_jaws.json": ("Custom grippers: clips, arms, collision check, JSON", "application/json"),
    "custom_jaws_preview.stl": ("Custom grippers on the SO-101, preview STL", "model/stl"),
    "custom_jaws_scissors.stl": ("The scissors in the custom grippers, preview STL", "model/stl"),
    "custom_jaws_moving_part.stl": ("Animation: the moving jaw", "model/stl"),
    "custom_jaws_fixed_part.stl": ("Animation: the fixed part", "model/stl"),
    "custom_jaws_moving_blade.stl": ("Animation: the moving half of the scissors", "model/stl"),
    "custom_jaws_fixed_blade.stl": ("Animation: the fixed half of the scissors", "model/stl"),
    "custom_jaws_sim.xml": ("The MuJoCo model of the custom grippers working the scissors", "application/xml"),
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
MIN_PHOTOS, MAX_PHOTOS = 8, 40     # the guided set is 11: 6 at 45 degrees, 4 low, 1 from above
ID = re.compile(r"^[a-z0-9-]{4,64}$")
# Deployed, a scan or a CAD agent run needs the passcode and counts against a daily cap, so the
# Meta and Modal credits cannot be run down. Both are off unless set (the local app stays open).
PASSCODE = os.environ.get("BEVELL3D_PASSCODE", "")
DAILY_CAP = int(os.environ.get("BEVELL3D_DAILY_CAP", "0") or 0)
# Anyone may run one on their own Meta Model API key instead (header x-model-api-key). The key
# goes to the run's own process in memory and is written nowhere. SAM 3D still runs on our Modal
# GPUs, so those runs have a cap of their own (0: none), and BEVELL3D_BYOK_SAM3D=0 leaves SAM 3D out.
BYOK_DAILY_CAP = int(os.environ.get("BEVELL3D_BYOK_DAILY_CAP", "200") or 0)
BYOK_SAM3D = os.environ.get("BEVELL3D_BYOK_SAM3D", "1") != "0"
# Visible ASCII only, so no whitespace, and at least 8 characters, so masking it cannot touch
# ordinary text. Never checked against the API: a key it refuses fails the run's first call.
KEY_FORM = re.compile(r"^[\x21-\x7e]{8,512}$")
# Or a Bevell Unlimited subscriber's Bevell API key (bvl_..., in the same field): bevell.app says
# whether its account is subscribed, and the run goes on our Meta key, as with the passcode. The
# Bevell key goes no further than that check. Each account has its own daily cap.
BEVELL_PREFIX = "bvl_"
BEVELL_ACCOUNT_URL = os.environ.get("BEVELL3D_ACCOUNT_URL", "https://bevell.app/api/v1/account")
UNLIMITED_DAILY_CAP = int(os.environ.get("BEVELL3D_UNLIMITED_DAILY_CAP", "20") or 0)
VERDICT_S, REFUSAL_S = 600, 60              # how long bevell.app's answer is kept, by sha256 of the key
NOT_RECOGNISED = "That Bevell API key was not recognised. Make one at bevell.app/developers."
NO_UNLIMITED = "That key's account has no Bevell Unlimited. Get it at bevell.app/pricing."
_verdicts = {}
usage_lock, verdict_lock = threading.Lock(), threading.Lock()


def _own_key(request):
    key = request.headers.get("x-model-api-key", "")
    if key and not KEY_FORM.match(key):
        raise HTTPException(400, "That API key doesn't look right. Paste it again, with no spaces.")
    return key or None


def _ask_bevell(key):
    import requests
    return requests.get(BEVELL_ACCOUNT_URL, headers={"Authorization": "Bearer " + key}, timeout=10)


def _unlimited_account(key):
    """The account id behind a Bevell API key whose account has Bevell Unlimited, or the
    HTTPException that says why not. Only a hash of the key is kept, never the key."""
    h = hashlib.sha256(key.encode()).hexdigest()
    with verdict_lock:
        hit = _verdicts.get(h)
    if hit and hit[0] > time.time():
        if isinstance(hit[1], HTTPException):
            raise hit[1]
        return hit[1]
    try:
        r = _ask_bevell(key)
        body = r.json() if r.status_code == 200 else {}
    except Exception as e:                      # the network, a timeout, a page that is not JSON
        print("Bevell account check failed:", type(e).__name__, flush=True)
        raise HTTPException(503, "Could not check your Bevell subscription. Try again.")
    if r.status_code == 200 and (body.get("subscription") or {}).get("status") in ("active", "trialing") and body.get("id"):
        verdict, keep = str(body["id"]), VERDICT_S
    elif r.status_code in (401, 403):
        verdict, keep = HTTPException(401, NOT_RECOGNISED), REFUSAL_S
    elif r.status_code in (200, 402):
        verdict, keep = HTTPException(402, NO_UNLIMITED), REFUSAL_S
    else:
        print("Bevell account check failed: HTTP", r.status_code, flush=True)
        raise HTTPException(503, "Could not check your Bevell subscription. Try again.")
    with verdict_lock:
        _verdicts[h] = (time.time() + keep, verdict)
    if isinstance(verdict, HTTPException):
        raise verdict
    return verdict


def _check_access(request):
    """Who pays for the run, as (the Meta key for the run, the cap it counts against). The
    visitor's own Meta key runs on itself; a Bevell Unlimited key or the passcode on ours (None)."""
    key = _own_key(request)
    if key and key.startswith(BEVELL_PREFIX):
        return None, f"unlimited {_unlimited_account(key)}"
    if key:
        return key, "own-key"
    given = request.headers.get("x-passcode", "").strip()
    if PASSCODE and not hmac.compare_digest(given.lower(), PASSCODE.lower()):
        raise HTTPException(401, "That passcode isn't right." if given else
                            "Enter the passcode, your own Meta Model API key, or a Bevell API key.")
    return None, ""


def _count_run(bucket=""):
    """Count one run against today's cap (UTC); refuse when it is used up. Own Meta keys share
    a cap of their own, and each Bevell Unlimited account has its own."""
    unlimited = bucket.startswith("unlimited")
    cap = BYOK_DAILY_CAP if bucket == "own-key" else UNLIMITED_DAILY_CAP if unlimited else DAILY_CAP
    if not cap:
        return
    path = os.path.join(SCANS, "_usage.json")
    today = time.strftime("%Y-%m-%d", time.gmtime())
    name = f"{bucket} {today}" if bucket else today
    with usage_lock:
        use = json.load(open(path)) if os.path.exists(path) else {}
        if use.get(name, 0) >= cap:
            raise HTTPException(429, f"Today's {cap} runs on your Bevell Unlimited account are used up. Try again tomorrow."
                                if unlimited else f"Today's {cap} runs on visitors' own keys are used up. Try again tomorrow, or see the examples."
                                if bucket else f"Today's {cap} runs are used up. Try again tomorrow, or see the examples.")
        use = {k: v for k, v in use.items() if k.endswith(today)}      # only today's counts are kept
        use[name] = use.get(name, 0) + 1
        os.makedirs(SCANS, exist_ok=True)
        json.dump(use, open(path + ".tmp", "w")); os.replace(path + ".tmp", path)


# ---------- in a run's own process: the visitor's key, used and masked out of everything ----------
_SECRET = ""


def _forms():
    """The key as it could appear in text: as is, JSON-escaped, repr'd or URL-encoded."""
    s = _SECRET
    return sorted({s, json.dumps(s)[1:-1], repr(s)[1:-1], quote(s, safe="")}, key=len, reverse=True) if s else []


def _scrub(x):
    """x with the key masked, all the way down, by as many asterisks as it has characters."""
    if not _SECRET:
        return x
    if isinstance(x, str):
        for f in _forms():
            x = x.replace(f, "*" * len(f))
        return x
    if isinstance(x, dict):
        return {_scrub(k): _scrub(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_scrub(v) for v in x]
    return x


class _Scrubbed:
    """stdout or stderr, masking the key in whatever is printed (tracebacks included)."""
    def __init__(self, stream):
        self._stream = stream

    def write(self, s):
        return self._stream.write(_scrub(s) if isinstance(s, str) else s)

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _use_key(key):
    """Every Meta Model API call in this process uses the visitor's key. Called before any
    bevell3d import, since sam_client reads the key when it is imported."""
    global _SECRET
    if not key:
        return
    _SECRET = key
    os.environ["MODEL_API_KEY"] = key
    if "bevell3d.sam_client" in sys.modules:         # imported already: set it there too
        sys.modules["bevell3d.sam_client"].KEY = key
    sys.stdout, sys.stderr = (_Scrubbed(s) if s is not None else s for s in (sys.stdout, sys.stderr))


def _sweep(folder):
    """Mask the key in any file the run wrote under the scan folder, should an API error that
    quotes it have been saved. The mask is as long as the key, so a binary file keeps its layout.
    upload/ holds the visitor's photos as sent, written before the run, so it is left alone."""
    if not _SECRET:
        return
    forms = [f.encode() for f in _forms()]
    for root, dirs, names in os.walk(folder):
        if root == folder and "upload" in dirs:
            dirs.remove("upload")
        for n in names:
            p = os.path.join(root, n)
            try:
                data = open(p, "rb").read()
                if any(f in data for f in forms):
                    for f in forms:
                        data = data.replace(f, b"*" * len(f))
                    open(p + ".tmp", "wb").write(data); os.replace(p + ".tmp", p)
            except OSError:
                continue


app = FastAPI(title="Bevell 3D")
lock = threading.Lock()


def _status(scan_id, **kw):
    path = os.path.join(SCANS, scan_id, "status.json")
    st = json.load(open(path)) if os.path.exists(path) else {}
    st.update(kw, updated=time.time())
    st = _scrub(st)
    json.dump(st, open(path + ".tmp", "w"), default=float)
    os.replace(path + ".tmp", path)
    return st


SCAN_TIMEOUT_S = int(os.environ.get("BEVELL3D_SCAN_TIMEOUT", "1200"))
AGENT_TIMEOUT_S = int(os.environ.get("BEVELL3D_AGENT_TIMEOUT", "1800"))


def friendly(e, own_key=False):
    """What the person sees. Our own refusals (ValueError) are written for people; anything else
    is ours to fix, so it says so, and the detail stays in the status file. On an own key, the
    Meta Model API refusing it is theirs to fix, so that says so instead."""
    if isinstance(e, ValueError) and str(e):
        return _scrub(str(e))
    status = getattr(getattr(e, "response", None), "status_code", None)
    if own_key and status in (401, 403):
        return "The Meta Model API turned your key down. Check it and try again."
    if own_key and status in (402, 429):
        return "The Meta Model API says your key is out of credit or over its rate limit. Try again later."
    return "Something went wrong on our side. Try again; if it happens again, tell us."


def _detail(e):
    return _scrub(f"{type(e).__name__}: {e}")[:500]              # masked before it is cut short


def _scan_child(scan_id, paths, scans_dir, key=None, sam3d=True):
    """The pipeline in a process of its own (spawned), writing its progress to status.json.
    `key`: the visitor's own Meta Model API key, when the run is on theirs."""
    global SCANS
    SCANS = scans_dir
    _use_key(key)
    started = time.time()
    done = []

    def progress(stage, detail=""):
        st = json.load(open(os.path.join(SCANS, scan_id, "status.json")))
        if st.get("stage") and st["stage"] != stage and st["stage"] not in done:
            done.append(st["stage"])
        _status(scan_id, stage=stage, detail=detail, done=done, elapsed=round(time.time() - started, 1))

    try:
        from bevell3d.run import run
        tool = json.load(open(os.path.join(SCANS, scan_id, "status.json"))).get("mode") == "gripper"
        summary = run(paths, os.path.join(SCANS, scan_id, "result"), log=lambda *a: None, progress=progress, tool=tool,
                      use_sam3d=sam3d)
        _status(scan_id, state="done", stage="done", elapsed=round(time.time() - started, 1), summary=summary)
    except Exception as e:
        traceback.print_exc()
        _status(scan_id, state="failed", error=friendly(e, bool(key)), error_detail=_detail(e),
                elapsed=round(time.time() - started, 1))
    finally:
        _sweep(os.path.join(SCANS, scan_id))


def _agent_child(scan_id, scans_dir, key=None):
    global SCANS
    SCANS = scans_dir
    _use_key(key)
    res = os.path.join(SCANS, scan_id, "result")
    started = time.time()

    def log(msg):
        _status(scan_id, agent={"state": "running", "detail": _scrub(str(msg))[:160], "elapsed": round(time.time() - started)})

    log("Muse Spark is writing the CAD")
    try:
        from bevell3d.agent_cad import run_agent
        rep = run_agent(res, rounds=2, log=log)
        _status(scan_id, agent={"state": "done", "report": rep, "elapsed": round(time.time() - started)})
    except Exception as e:
        traceback.print_exc()
        _status(scan_id, agent={"state": "failed", "error": friendly(e, bool(key)), "error_detail": _detail(e)})
    finally:
        _sweep(os.path.join(SCANS, scan_id))


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


def _work(scan_id, paths, key=None, sam3d=True, target=None, timeout=None):
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
        _in_child(target or _scan_child, (scan_id, paths, SCANS, key, sam3d), timeout or SCAN_TIMEOUT_S, stopped)


@app.get("/api/config")
def config():
    return {"passcode": bool(PASSCODE), "daily_cap": DAILY_CAP, "byok": True, "byok_daily_cap": BYOK_DAILY_CAP,
            "unlimited": True, "unlimited_daily_cap": UNLIMITED_DAILY_CAP}


@app.post("/api/scans")
async def create_scan(request: Request, photos: list[UploadFile] = File(...), mode: str = Form("scan")):
    key, bucket = await run_in_threadpool(_check_access, request)      # may ask bevell.app
    if not (MIN_PHOTOS <= len(photos) <= MAX_PHOTOS):
        raise HTTPException(400, f"Upload {MIN_PHOTOS} to {MAX_PHOTOS} photos; you sent {len(photos)}.")
    _count_run(bucket)
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
    threading.Thread(target=_work, args=(scan_id, paths, key, BYOK_SAM3D if key else True), daemon=True).start()
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
    if _photo_path(scan_id, st):
        st["photo"] = f"{base}/api/scans/{scan_id}/photo"
    return JSONResponse(st)


def _photo_path(scan_id, st=None):
    """One photo of the object as it was taken, for the viewer's Original tab: the one SAM 3D
    rebuilt it from when it did, else the middle of the set (a side view, not the first from above)."""
    d = os.path.join(SCANS, scan_id, "result", "photos")
    if not os.path.isdir(d):
        return None
    names = sorted(n for n in os.listdir(d) if n.lower().endswith((".jpg", ".jpeg", ".png")))
    if not names:
        return None
    used = (((st or {}).get("summary") or {}).get("sam3d") or {}).get("photo")
    for n in names:
        if used and os.path.splitext(n)[0] == used:
            return os.path.join(d, n)
    return os.path.join(d, names[len(names) // 2])


@app.get("/api/scans/{scan_id}/photo")
def scan_photo(scan_id: str):
    if not ID.match(scan_id) or not os.path.exists(os.path.join(SCANS, scan_id, "status.json")):
        raise HTTPException(404, "No scan with that id.")
    p = _photo_path(scan_id, json.load(open(os.path.join(SCANS, scan_id, "status.json"))))
    if not p:
        raise HTTPException(404, "No photo kept for that scan.")
    return FileResponse(p, media_type="image/png" if p.endswith(".png") else "image/jpeg")


@app.get("/api/scans/{scan_id}/files/{name}")
def scan_file(scan_id: str, name: str):
    if not ID.match(scan_id) or name not in FILES:
        raise HTTPException(404, "No such file.")
    p = os.path.join(SCANS, scan_id, "result", name)
    if not os.path.exists(p):
        raise HTTPException(404, "Not made yet.")
    return FileResponse(p, media_type=FILES[name][1], filename=f"bevell-{scan_id}-{name}")


def _agent(scan_id, key=None):
    with lock:
        def stopped(why):
            st = json.load(open(os.path.join(SCANS, scan_id, "status.json")))
            if (st.get("agent") or {}).get("state") in ("done", "failed"):
                return
            _status(scan_id, agent={"state": "failed", "error_detail": why,
                                    "error": "Writing the CAD took too long, so it was stopped. Try again." if why == "timeout"
                                    else "Writing the CAD stopped unexpectedly. Try again."})
        _in_child(_agent_child, (scan_id, SCANS, key), AGENT_TIMEOUT_S, stopped)


@app.post("/api/scans/{scan_id}/agent")
def start_agent(scan_id: str, request: Request):
    """Muse Spark writes the object as an editable CAD program; the photos tune and check it. On
    an own key, the request brings it again: the scan's was never kept."""
    key, bucket = _check_access(request)
    res = os.path.join(SCANS, scan_id, "result")
    if not ID.match(scan_id) or not os.path.exists(os.path.join(res, "views.pkl")):
        raise HTTPException(404, "That scan has no photos to check CAD against.")
    _count_run(bucket)
    _status(scan_id, agent={"state": "queued", "detail": "starting"})
    threading.Thread(target=_agent, args=(scan_id, key), daemon=True).start()
    return {"ok": True}


# Kept on the volume but not offered: the clock's hull beat its SAM 3D model on agreement and
# came out a blob that looks nothing like the photos.
HIDDEN_EXAMPLES = {"example-clock"}


@app.get("/api/examples")
def examples():
    out = []
    for d in sorted(os.listdir(SCANS)) if os.path.isdir(SCANS) else []:
        if d.startswith("example-") and d not in HIDDEN_EXAMPLES and os.path.exists(os.path.join(SCANS, d, "status.json")):
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
