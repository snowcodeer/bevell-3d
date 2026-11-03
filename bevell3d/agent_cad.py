"""Agentic CAD: Muse Spark writes the object as a parametric CadQuery program; the photos verify it.

The model chooses the features (a revolved body, a swept handle, fillets) and names the
dimensions with sensible ranges. It never sets a final number: an optimiser tunes every
dimension and the placement until the program's outline matches the object in every
calibrated photo. Muse Spark then sees where they still disagree, colour-coded per photo, and
may revise the program. The best-scoring program wins and is written out as STEP, as the
script itself and as its parameters, so the result is an editable feature model.

    .venv/bin/python -m bevell3d.agent_cad out/bench/bottle/full --rounds 3
"""
import argparse, base64, builtins, io, json, math, multiprocessing as mp, os, pickle, time
import numpy as np, cv2, requests, trimesh
from PIL import Image
from scipy.optimize import minimize
from .project import silhouette, iou
from .fit import silhouette_mask_small

BASE = os.environ.get("MODEL_API_BASE", "https://api.meta.ai/v1")
MODEL = os.environ.get("AGENT_MODEL", "muse-spark-1.3")
SCALE = 0.25            # silhouettes are compared at a quarter of the working resolution

SAFE = {k: getattr(builtins, k) for k in (
    "abs", "min", "max", "range", "len", "float", "int", "round", "sum", "enumerate", "zip", "list", "tuple",
    "dict", "sorted", "reversed", "map", "any", "all", "isinstance", "ValueError", "Exception", "pow", "bool")}


# --- running a program, out of process ------------------------------------------------------

def _build(program, params, tol, step_path=None):
    """In a worker process: build a feature tree (dict) or run a program (str), return its
    tessellation, and write STEP if asked."""
    import cadquery as cq
    if isinstance(program, dict):
        from .feature_tree import to_cadquery
        shape, _ = to_cadquery(program, dict(params))
    else:
        ns = {"cq": cq, "math": math, "__builtins__": SAFE}
        exec(compile(program, "<muse-spark>", "exec"), ns)
        res = ns["build"](dict(params))
        if isinstance(res, cq.Workplane):
            vals = [v for v in res.vals() if isinstance(v, cq.Shape)]
            shape = vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
        else:
            shape = res
    solids = shape.Solids()
    if not solids:
        raise ValueError("build(p) returned no solid")
    if len(solids) > 1:
        shape = solids[0].fuse(*solids[1:]).clean()
    vs, fs = shape.tessellate(tol, 0.35)
    if step_path:
        cq.exporters.export(cq.Workplane().add(shape), step_path)
    bb = shape.BoundingBox()
    return np.array([v.toTuple() for v in vs], float), np.array(fs, int), float(shape.Volume()), (bb.xlen, bb.ylen, bb.zlen)


class Builder:
    """One worker process; a program that hangs the kernel is killed and the worker replaced."""
    def __init__(self):
        self._new()

    def _new(self):
        self.pool = mp.get_context("spawn").Pool(1)

    def build(self, code, params, tol=0.4, timeout=25, step_path=None):
        r = self.pool.apply_async(_build, (code, params, tol, step_path))
        try:
            return r.get(timeout)
        except mp.TimeoutError:
            self.pool.terminate(); self._new()
            raise TimeoutError(f"the program took over {timeout} s")

    def close(self):
        self.pool.terminate()


# --- scoring against the photos -------------------------------------------------------------

def _rotz(deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def placed(verts, faces, pose):
    """Put a program's solid (built round the origin, base on z = 0) on the sheet at pose (x, y, yaw)."""
    x, y, yaw = pose
    v = verts @ _rotz(yaw).T
    v[:, 2] -= v[:, 2].min()
    v[:, 0] += x - (v[:, 0].max() + v[:, 0].min()) / 2
    v[:, 1] += y - (v[:, 1].max() + v[:, 1].min()) / 2
    return trimesh.Trimesh(v, faces, process=False)


class Scorer:
    def __init__(self, views, masks, size):
        self.views, self.size = views, size
        self.small = [silhouette_mask_small(m, SCALE) for m in masks]

    def __call__(self, mesh):
        return float(np.mean([iou(silhouette(mesh, v, self.size, SCALE), m) for v, m in zip(self.views, self.small)]))

    def per_view(self, mesh):
        return [iou(silhouette(mesh, v, self.size, SCALE), m) for v, m in zip(self.views, self.small)]


def optimise(builder, scorer, code, spec, centre, rounds_fev=160, log=print):
    """Tune every parameter (inside its range) and the placement for the best mean IoU."""
    names = [p["name"] for p in spec]
    lo = np.array([float(p["min"]) for p in spec]); hi = np.array([float(p["max"]) for p in spec])
    x0 = np.clip((np.array([float(p["value"]) for p in spec]) - lo) / np.maximum(hi - lo, 1e-9), 0, 1)
    cache = {}

    def mesh_for(u):
        key = tuple(np.round(np.clip(u, 0, 1), 4))
        if key not in cache:
            params = dict(zip(names, (lo + np.clip(u, 0, 1) * (hi - lo)).tolist()))
            try:
                cache[key] = builder.build(code, params)
            except Exception:
                cache[key] = None
        return cache[key]

    first = mesh_for(x0)
    if first is None:
        return None
    # Placement: the hull's centre, and the turn that best matches at the starting parameters.
    best_yaw = max(range(0, 180, 15), key=lambda yaw: scorer(placed(first[0], first[1], (centre[0], centre[1], yaw))))

    def f(z):
        u, (dx, dy, dyaw) = z[:-3], z[-3:]
        pen = float(np.sum(np.clip(-u, 0, None) + np.clip(u - 1, 0, None)))
        m = mesh_for(u)
        if m is None:
            return 1.0 + pen
        return -scorer(placed(m[0], m[1], (centre[0] + dx, centre[1] + dy, best_yaw + dyaw))) + pen

    z0 = np.r_[x0, 0.0, 0.0, 0.0]
    steps = np.r_[np.full(len(x0), 0.12), 3.0, 3.0, 8.0]
    simplex = np.vstack([z0] + [z0 + np.eye(len(z0))[k] * steps[k] for k in range(len(z0))])
    t = time.time()
    r = minimize(f, z0, method="Nelder-Mead", options={"initial_simplex": simplex, "maxfev": rounds_fev, "xatol": 1e-3, "fatol": 1e-4})
    u = np.clip(r.x[:-3], 0, 1)
    params = dict(zip(names, (lo + u * (hi - lo)).tolist()))
    pose = (centre[0] + r.x[-3], centre[1] + r.x[-2], best_yaw + r.x[-1])
    log(f"  optimised {len(names)} parameters in {r.nfev} builds, {time.time() - t:.0f} s: IoU {-r.fun:.3f}")
    return {"params": params, "pose": pose, "iou": float(-r.fun), "builds": int(r.nfev)}


# --- talking to Muse Spark ------------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {
        "features": {"type": "string", "description": "one line: the features, in order"},
        "parameters": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "value": {"type": "number"}, "min": {"type": "number"},
            "max": {"type": "number"}, "what": {"type": "string"}},
            "required": ["name", "value", "min", "max", "what"], "additionalProperties": False}},
        "code": {"type": "string"},
    },
    "required": ["features", "parameters", "code"],
    "additionalProperties": False,
}

TREE_SCHEMA = {
    "type": "object",
    "properties": {
        "features": {"type": "string"},
        "parameters": SCHEMA["properties"]["parameters"],
        "steps": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["features", "parameters", "steps"],
}

TREE_BRIEF = """You are a CAD engineer. Rebuild the object in the photos as a clean parametric
feature tree, the kind a designer builds in Fusion 360, as JSON.

Return {"features": one line, "parameters": [...], "steps": [...]}.
Parameters: {"name", "value", "min", "max", "what"}, in millimetres or degrees, 3 to 8 of them.
Give each a range wide enough for the true value: an optimiser tunes the values against the
photos, so the ranges matter more than your guesses.
Every size in a step is a number or an expression in the parameters, as a string:
"body_d / 2", "h * 0.75", "min(a, b)". Allowed: + - * / ** min max sqrt sin cos tan abs.

Frame: millimetres; Z up; the object rests on z = 0 the way it sits in the photos; centred on
x = y = 0; its longest horizontal side along X.

Steps, in order (the first must make a solid):
- revolve: {"id", "op": "revolve", "profile": [[r, z], ...]} a closed outline in the (r, z)
  half-plane, r >= 0, turned 360 degrees about Z. Start and end on the axis (r = 0).
- extrude: {"id", "op": "extrude", "shape": SHAPE, "from_z": z, "height": h, "mode": "add" or "cut"}
- loft: {"id", "op": "loft", "sections": [{"z": z, "shape": SHAPE}, ...]}
- sweep: {"id", "op": "sweep", "section": SHAPE, "path": {"plane": "XZ" or "YZ", "points": [[a, b], ...]}}
  a section along a smooth path through the points (XZ: a is x, b is z). Handles are sweeps.
- shell: {"id", "op": "shell", "thickness": t, "open": "top" or "none"} hollows the body.
- fillet / chamfer: {"id", "op": "fillet", "edges": "top" | "bottom" | "vertical" | "all", "radius": r}
SHAPE: {"circle": {"d": d}} | {"rect": {"w": w, "l": l}} | {"ellipse": {"w": w, "l": l}} |
       {"polygon": [[x, y], ...]}, each with an optional "at": [x, y].
Use few, real features. Do not model printing, labels or text. Keep fillet radii well below
the edges they round.

Example, a mug:
{"features": "revolved body, shell open at the top, swept handle",
 "parameters": [{"name": "d", "value": 82, "min": 60, "max": 100, "what": "outer diameter"},
   {"name": "h", "value": 95, "min": 70, "max": 120, "what": "height"},
   {"name": "wall", "value": 4, "min": 2, "max": 8, "what": "wall"},
   {"name": "reach", "value": 28, "min": 15, "max": 45, "what": "handle reach"},
   {"name": "grip", "value": 11, "min": 6, "max": 16, "what": "handle thickness"}],
 "steps": [{"id": "body", "op": "revolve", "profile": [[0, 0], ["d/2", 0], ["d/2", "h"], [0, "h"]]},
   {"id": "hollow", "op": "shell", "thickness": "wall", "open": "top"},
   {"id": "handle", "op": "sweep", "section": {"circle": {"d": "grip"}},
    "path": {"plane": "XZ", "points": [["d/2 - wall", "h*0.78"], ["d/2 + reach", "h*0.55"], ["d/2 - wall", "h*0.25"]]}}]}
"""

BRIEF = """You are a CAD engineer. Rebuild the object in the photos as a clean parametric CadQuery
model that a designer would be happy to edit.

Write Python defining `def build(p):` that returns a cq.Workplane (or cq.Shape) holding one solid.
`p` is a dict of the parameters you declare, in millimetres or degrees. `cq` and `math` are
already available; do not import anything, read files or print.

Conventions: millimetres; Z up; the object rests on z = 0 the way it sits in the photos; centred
on x = y = 0; its longest horizontal side along X.

Use real CAD features: sketches, extrude, revolve (cq.Workplane("XZ") profile, .revolve(360,
(0, 0, 0), (0, 1, 0)) turns about the Z axis), loft, sweep along a path, shell, fillet, chamfer,
union, cut. Prefer few features and few parameters (3 to 8). Give every dimension a parameter
with a range wide enough for the true value: an optimiser will tune the values against the
photos, so the ranges matter more than your guesses. Do not model printing on labels or text.

Fillet and shell are the commonest failures: keep fillet radii parameters well below the wall
or edge they round, and wrap risky fillets so the build still succeeds:
    try:
        body = body.edges(">Z").fillet(p["top_round"])
    except Exception:
        pass

Example, a bottle with a cap:
def build(p):
    body = (cq.Workplane("XY").circle(p["body_d"] / 2).extrude(p["body_h"]))
    try:
        body = body.edges(">Z").fillet(p["shoulder"])
    except Exception:
        pass
    cap = cq.Workplane("XY").workplane(offset=p["body_h"]).circle(p["cap_d"] / 2).extrude(p["cap_h"])
    return body.union(cap)
"""


def _img_url(arr_or_path, max_side=900):
    im = Image.open(arr_or_path) if isinstance(arr_or_path, str) else Image.fromarray(arr_or_path)
    im = im.convert("RGB"); im.thumbnail((max_side, max_side))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def ask(messages, key=None, timeout=300, mode="tree"):
    key = key or os.environ["MODEL_API_KEY"]
    fmt = {"name": "feature_tree", "strict": False, "schema": TREE_SCHEMA} if mode == "tree" else \
          {"name": "cad_program", "strict": True, "schema": SCHEMA}
    body = {"model": MODEL, "max_tokens": 12000, "messages": messages,
            "response_format": {"type": "json_schema", "json_schema": fmt}}
    r = requests.post(BASE + "/chat/completions", headers={"Authorization": "Bearer " + key}, json=body, timeout=timeout)
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    return json.loads(msg["content"]), msg


def first_messages(photo_paths, plan, extents, mode="tree"):
    text = ((TREE_BRIEF if mode == "tree" else BRIEF) + f"\n\nThe object: {plan['object']} (planner's route: {plan['route']}).\n"
            f"Measured from the photos, its outer size is about {extents[0]:.1f} × {extents[1]:.1f} × {extents[2]:.1f} mm "
            "(width × depth × height; these are an outer bound and can run 1 to 3 mm large). "
            + ("Return the feature tree." if mode == "tree" else "Return the features, the parameters and the code."))
    return [{"role": "user", "content": [{"type": "text", "text": text}] + [{"type": "image_url", "image_url": {"url": _img_url(p)}} for p in photo_paths]}]


def diff_sheet(scorer, mesh, photos, picks):
    """Per photo: grey where model and photo agree, red where the photo has object the model lacks,
    cyan where the model has material the photo does not."""
    tiles = []
    for i in picks:
        v, m = scorer.views[i], scorer.small[i]
        s = silhouette(mesh, v, scorer.size, SCALE)
        img = cv2.resize(cv2.imread(photos[i]), (m.shape[1], m.shape[0])) // 3
        img[m & s] = (150, 150, 150); img[m & ~s] = (40, 40, 230); img[~m & s] = (230, 210, 40)
        ys, xs = np.nonzero(m | s)
        if len(xs):
            pad = 12; img = img[max(0, ys.min() - pad):ys.max() + pad, max(0, xs.min() - pad):xs.max() + pad]
        img = cv2.resize(img, (260, int(260 * img.shape[0] / max(1, img.shape[1]))))
        cv2.putText(img, f"IoU {iou(s, m):.2f}", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        tiles.append(img)
    h = max(t.shape[0] for t in tiles)
    row = np.hstack([cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, 6, cv2.BORDER_CONSTANT, value=(20, 22, 26)) for t in tiles])
    return cv2.cvtColor(row, cv2.COLOR_BGR2RGB)


# --- the loop -------------------------------------------------------------------------------

def run_agent(out_dir, rounds=3, log=print, key=None, mode="tree"):
    """out_dir: a finished scan (views.pkl, plan.json, hull.stl, photos/). Writes agent_*.json/.py/.step."""
    vp = pickle.load(open(os.path.join(out_dir, "views.pkl"), "rb"))
    views, masks, size = vp["views"], vp["masks"], vp["size"]
    plan = json.load(open(os.path.join(out_dir, "plan.json")))
    hull = trimesh.load(os.path.join(out_dir, "hull.stl"))
    photos = [os.path.join(out_dir, "photos", v["name"] + ".jpg") for v in views]
    centre = (hull.bounds[0][:2] + hull.bounds[1][:2]) / 2
    scorer = Scorer(views, masks, size)
    hull_iou = scorer(hull)
    elev = []
    for v in views:
        R, _ = cv2.Rodrigues(v["rv"]); c = (-R.T @ v["tv"]).ravel() - hull.bounding_box.centroid
        elev.append(math.degrees(math.atan2(c[2], math.hypot(c[0], c[1]))))
    picks = sorted({int(np.argmin([abs(e - t) for e in elev])) for t in (45, 10, 85)})
    messages = first_messages([photos[i] for i in picks], plan, hull.extents, mode)
    builder = Builder()
    history, best = [], None
    t0 = time.time()
    try:
        for rnd in range(1, rounds + 1):
            prog, reply = None, None
            for attempt in range(3):                      # a program that will not build gets its error back
                prog, reply = ask(messages, key, mode=mode)
                spec = prog["parameters"]
                try:
                    if mode == "tree":
                        from .feature_tree import validate
                        validate(prog)
                        prog["code"] = {"parameters": prog["parameters"], "steps": prog["steps"]}
                    builder.build(prog["code"], {p["name"]: p["value"] for p in spec})
                    break
                except Exception as e:
                    log(f"round {rnd}: program failed ({type(e).__name__}: {str(e)[:120]}); asking for a fix")
                    messages += [{"role": "assistant", "content": json.dumps({k: v for k, v in prog.items() if k != "code" or mode == "code"})},
                                 {"role": "user", "content": f"That {'tree' if mode == 'tree' else 'program'} failed: {type(e).__name__}: {str(e)[:400]}. Return a corrected version."}]
                    prog = None
            if prog is None:
                break
            log(f"round {rnd}: {prog['features']} ({len(prog['parameters'])} parameters)")
            res = optimise(builder, scorer, prog["code"], prog["parameters"], centre, log=log)
            if res is None:
                break
            verts, faces, vol, bbox = builder.build(prog["code"], res["params"])
            mesh = placed(verts, faces, res["pose"])
            # Size from the shape itself: the kernel's bounding box runs loose on lofts and
            # splines (a mouse loft reported 136 mm for a 125 mm solid).
            entry = {"round": rnd, "features": prog["features"], "iou": res["iou"], "builds": res["builds"],
                     "params": res["params"], "spec": prog["parameters"], "code": prog["code"], "pose": res["pose"],
                     "size_mm": [round(float(e), 1) for e in mesh.extents]}
            history.append(entry)
            if best is None or entry["iou"] > best["iou"]:
                best = entry
            if rnd == rounds:
                break
            per = scorer.per_view(mesh)
            worst = list(np.argsort(per)[:2]); show = sorted(set(worst) | {picks[0]})
            sheet = diff_sheet(scorer, mesh, photos, show)
            Image.fromarray(sheet).save(os.path.join(out_dir, f"agent_diff_round{rnd}.jpg"))
            fitted = ", ".join(f"{k} {v:.1f}" for k, v in res["params"].items())
            messages += [{"role": "assistant", "content": json.dumps({k: v for k, v in prog.items() if k != "code" or mode == "code"})},
                         {"role": "user", "content": [
                             {"type": "text", "text": (
                                 f"Tuned against all {len(views)} photos, your program reaches a mean IoU of {res['iou']:.3f} "
                                 f"(the measured hull reaches {hull_iou:.3f}). Fitted values: {fitted}. "
                                 "In the image, per photo: grey = model and photo agree, red = object the model is missing, "
                                 "cyan = model material the object does not have. Revise the program to fix the biggest "
                                 "disagreement: add, remove or change features, widen a range that hit its limit. Keep it "
                                 f"clean and editable. Return the full {'tree' if mode == 'tree' else 'program'}.")},
                             {"type": "image_url", "image_url": {"url": _img_url(sheet, 1200)}}]}]
        if best:
            step = os.path.join(out_dir, "agent_model.step")
            builder.build(best["code"], best["params"], tol=0.1, step_path=step)
            v, f, _, _ = builder.build(best["code"], best["params"], tol=0.1)
            placed(v, f, best["pose"]).export(os.path.join(out_dir, "agent_model.stl"))
            if mode == "tree":
                from .feature_tree import write_fusion_script
                tree = {"features": best["features"], "parameters": [
                    {**q, "value": round(best["params"][q["name"]], 2)} for q in best["spec"]], "steps": best["code"]["steps"]}
                json.dump(tree, open(os.path.join(out_dir, "agent_tree.json"), "w"), indent=1)
                folder = write_fusion_script(os.path.join(out_dir, "fusion", "BevellModel"), tree, best["params"],
                                             f"{plan['object']}: {best['features']}", len(views))
                import shutil
                shutil.make_archive(os.path.join(out_dir, "agent_fusion"), "zip", os.path.join(out_dir, "fusion"))
            script = (f"# {plan['object']}: {best['features']}\n# Written by Muse Spark, dimensions fitted to "
                      f"{len(views)} calibrated photos (mean silhouette IoU {best['iou']:.3f}).\n"
                      "import cadquery as cq, math\n\n"
                      f"P = {json.dumps({k: round(v, 2) for k, v in best['params'].items()}, indent=4)}\n\n"
                      f"{best['code']}\n\nif __name__ == \"__main__\":\n    cq.exporters.export(build(P), \"model.step\")\n")
            if mode == "code":
                open(os.path.join(out_dir, "agent_model.py"), "w").write(script)
    finally:
        builder.close()
    report = {"object": plan["object"], "mode": mode, "hull_iou": hull_iou, "rounds": history, "best_round": best["round"] if best else None,
              "best_iou": best["iou"] if best else None, "seconds": round(time.time() - t0, 1)}
    json.dump(report, open(os.path.join(out_dir, "agent_report.json"), "w"), indent=1, default=float)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scan_dir")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--mode", choices=["tree", "code"], default="tree")
    a = ap.parse_args()
    rep = run_agent(a.scan_dir, a.rounds, mode=a.mode)
    print(json.dumps({k: v for k, v in rep.items() if k != "rounds"}, indent=1, default=float))
    for r in rep["rounds"]:
        print(f"round {r['round']}: IoU {r['iou']:.3f}, size {r['size_mm']} mm, {r['features']}")
