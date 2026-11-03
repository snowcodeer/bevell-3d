"""Photo set on an A4 sheet -> camera poses from the sheet -> visual hull at true scale.

Deterministic except for SAM's masks. Usage: python carve.py <name> <prompt> <img numbers...>
"""
import json, os, sys, pickle
import numpy as np, cv2, trimesh
from skimage import measure
from .sam_client import segment

A4 = (297.0, 210.0)          # mm, long x short
MAX_SIDE = 1536
F35 = 26.0                   # iPhone 16e main camera, 35 mm equivalent

def masks_for(n, prompt, cache):
    if n in cache:
        return cache[n]
    path = f"raw/IMG_{n}.jpg"
    im, s, obj = segment(path, prompt, MAX_SIDE)
    _, _, sheet = segment(path, "sheet of paper", MAX_SIDE)
    obj = max(obj, key=lambda r: r["mask"].sum()) if obj else None
    sheet = max(sheet, key=lambda r: r["mask"].sum()) if sheet else None
    cache[n] = {"size": im.size, "obj": None if obj is None else obj["mask"], "sheet": None if sheet is None else sheet["mask"]}
    return cache[n]

def sheet_quad(sheet_mask, obj_mask):
    m = (sheet_mask | obj_mask).astype(np.uint8) * 255   # the object sits on the sheet
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    hull = cv2.convexHull(max(cnts, key=cv2.contourArea))
    peri = cv2.arcLength(hull, True)
    for eps in np.linspace(0.01, 0.1, 40):
        q = cv2.approxPolyDP(hull, eps * peri, True)
        if len(q) == 4:
            return q.reshape(4, 2).astype(np.float64)
    return None

def orderings(q):
    """Every assignment of A4's corners that keeps a long edge first: two starts
    (180 deg apart) times two winding directions. The camera-above-the-sheet test
    in poses() keeps the right winding."""
    c = q.mean(0)
    ang = np.arctan2(q[:, 1] - c[1], q[:, 0] - c[0])
    q = q[np.argsort(ang)]
    out = []
    for qq in (q, q[::-1]):
        e = [np.linalg.norm(qq[i] - qq[(i + 1) % 4]) for i in range(4)]
        start = 0 if e[0] + e[2] >= e[1] + e[3] else 1       # edge 0->1 is a long edge
        for k in (start, start + 2):
            out.append(np.array([qq[(k + i) % 4] for i in range(4)]))
    return out

WORLD = np.array([[0, 0, 0], [A4[0], 0, 0], [A4[0], A4[1], 0], [0, A4[1], 0]], np.float64)

def intrinsics(w, h):
    f = F35 * np.hypot(w, h) / 43.27
    return np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])

def poses(q, K):
    res = []
    for o in orderings(q):
        ok, rv, tv = cv2.solvePnP(WORLD, o, K, None, flags=cv2.SOLVEPNP_IPPE)
        if ok:
            R, _ = cv2.Rodrigues(rv)
            if (-R.T @ tv)[2, 0] <= 0:      # the camera must be above the sheet
                continue
            proj, _ = cv2.projectPoints(WORLD, rv, tv, K, None)
            err = float(np.abs(proj.reshape(4, 2) - o).mean())
            res.append((rv, tv, err))
    return res

def project(pts, rv, tv, K):
    p, _ = cv2.projectPoints(pts, rv, tv, K, None)
    return p.reshape(-1, 2)

def inside(mask, uv):
    h, w = mask.shape
    u = np.round(uv[:, 0]).astype(int); v = np.round(uv[:, 1]).astype(int)
    inb = (u >= 0) & (u < w) & (v >= 0) & (v < h)
    hit = np.zeros(len(uv), bool)
    hit[inb] = mask[v[inb], u[inb]]
    return hit, inb

def grid(lo, hi, step):
    xs, ys, zs = [np.arange(lo[i], hi[i] + step / 2, step) for i in range(3)]
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    return np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1), (len(xs), len(ys), len(zs))

def carve(views, pts):
    keep = np.ones(len(pts), bool)
    for v in views:
        hit, inb = inside(v["mask"], project(pts, v["rv"], v["tv"], v["K"]))
        keep &= hit | ~inb          # outside the frame says nothing
    return keep

def main(name, prompt, nums):
    cache_path = f"cache_{name}.pkl"
    cache = pickle.load(open(cache_path, "rb")) if os.path.exists(cache_path) else {}
    views = []
    for n in nums:
        m = masks_for(n, prompt, cache)
        pickle.dump(cache, open(cache_path, "wb"))
        if m["obj"] is None or m["sheet"] is None:
            print(n, "skipped: no", "object" if m["obj"] is None else "sheet"); continue
        q = sheet_quad(m["sheet"], m["obj"])
        if q is None:
            print(n, "skipped: no 4-corner sheet"); continue
        w, h = m["size"]; K = intrinsics(w, h)
        if os.environ.get("ALLOW_EDGE") != "1" and any(p[0] < 4 or p[1] < 4 or p[0] > w - 5 or p[1] > h - 5 for p in q):
            print(n, "skipped: a sheet corner is outside the photo"); continue
        cands = poses(q, K)
        views.append({"n": n, "mask": m["obj"], "sheet": m["sheet"], "K": K, "cands": cands, "quad": q, "size": (w, h)})
        print(n, "corner reprojection px:", [round(c[2], 2) for c in cands])
    if os.environ.get("REFINE") == "1":
        from .refine import boundary_points, refine
        for v in views:
            v["bpts"] = boundary_points(v["sheet"], v["mask"])
        f0 = views[0]["K"][0, 0]
        f, before, after = refine(views, f0, views[0]["size"], os.environ.get("FREE_ASPECT") == "1")
        print(f"refined: focal {f:.0f}px (EXIF guess {f0:.0f}), median sheet-edge error {before:.1f} -> {after:.1f}px")
    # Coarse grid over the sheet, then choose each view's 180-degree ambiguity by agreement.
    pts, shape = grid((0, 0, 0), (A4[0], A4[1], 120), 2.0)
    # Each view's sheet can be labelled two ways round. Score every combination at once
    # (view 0 fixed) and keep the one where the most of the space survives every view.
    import itertools
    hits = []
    for v in views:
        per = []
        for rv, tv, _ in v["cands"]:
            v["rv"], v["tv"] = rv, tv
            per.append(carve([v], pts))
        hits.append(per)
    best = None
    for combo in itertools.product(*[range(len(h)) for h in hits[1:]]):
        k = hits[0][0].copy()
        for h, c in zip(hits[1:], combo):
            k &= h[c]
        if best is None or k.sum() > best[0]:
            best = (k.sum(), (0,) + combo, k)
    for v, c in zip(views, best[1]):
        v["rv"], v["tv"] = v["cands"][c][0], v["cands"][c][1]
    keep = best[2]
    print("labelling per view:", best[1], "kept coarse voxels:", int(best[0]))
    sel = pts[keep]
    lo = sel.min(0) - 4; hi = sel.max(0) + 4; lo[2] = 0
    if os.environ.get("SILREFINE") == "1":
        from .silrefine import refine_silhouettes
        slo = sel.min(0) - 20; shi = sel.max(0) + 20; slo[2] = 0
        hist = refine_silhouettes(views, slo, shi)
        print("silhouette agreement per round:", hist)
        pts2, _ = grid(slo, shi, 1.0)
        sel = pts2[carve(views, pts2)]
        lo = sel.min(0) - 4; hi = sel.max(0) + 4; lo[2] = 0
    # Fine grid over the object only.
    step = float(os.environ.get("STEP", "0.5"))
    fine, fshape = grid(lo, hi, step)
    occ = carve(views, fine).reshape(fshape)
    occ[:, :, 0] = occ[:, :, 1]     # sits on the sheet
    vol = np.pad(occ.astype(np.float32), 1)
    verts, faces, _, _ = measure.marching_cubes(vol, 0.5)
    verts = (verts - 1) * step + lo
    mesh = trimesh.Trimesh(verts, faces)
    if mesh.volume < 0:
        mesh.invert()
    if os.environ.get("SMOOTH", "1") == "1":
        trimesh.smoothing.filter_taubin(mesh, lamb=0.5, nu=-0.53, iterations=25)
    mesh.export(f"{name}_hull.stl")
    ext = mesh.bounding_box_oriented.primitive.extents
    print(json.dumps({"views": [v["n"] for v in views], "watertight": bool(mesh.is_watertight),
                      "volume_cm3": round(mesh.volume / 1000, 2), "oriented_extents_mm": [round(x, 1) for x in sorted(ext)]}))
    # Reprojection agreement with SAM per view.
    for v in views:
        hv = np.zeros_like(v["mask"], np.uint8)
        uv = project(mesh.vertices, v["rv"], v["tv"], v["K"]).astype(np.int32)
        cv2.fillPoly(hv, list(uv[mesh.faces]), 1)
        a, b = hv.astype(bool), v["mask"]
        print(v["n"], "IoU hull vs SAM:", round((a & b).sum() / max(1, (a | b).sum()), 3))
    pickle.dump([{k: v[k] for k in ("n", "rv", "tv", "K", "quad")} for v in views], open(f"{name}_views.pkl", "wb"))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
