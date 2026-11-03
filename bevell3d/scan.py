"""Photos on the capture sheet -> cameras -> SAM 3.1 masks -> visual hull at true scale.

    python -m bevell3d.scan --prompt "airpods case" --out out/airpods photos/IMG_*.HEIC
"""
import argparse, json, os, pickle
import numpy as np, cv2
from . import markers, photos
from .hull import visual_hull
from .project import silhouette, iou
from .sam_client import segment


def object_mask(path, prompt):
    """The most confident SAM 3.1 instance for the prompt, as a full-size boolean mask."""
    _, _, recs = segment(path, prompt, max_side=photos.MAX_SIDE)
    recs = [r for r in recs if "mask" in r]
    if not recs:
        return None
    return max(recs, key=lambda r: (r["conf"] or 0, r["mask"].sum()))["mask"]


def masks_for(prepared, prompt, cache_path, workers=4):
    """SAM 3.1 on every photo, four requests at a time (one at a time took most of a scan)."""
    from concurrent.futures import ThreadPoolExecutor
    cache = pickle.load(open(cache_path, "rb")) if os.path.exists(cache_path) else {}
    todo = [(name, path) for name, path in prepared if (name, prompt) not in cache]
    with ThreadPoolExecutor(workers) as pool:
        for (name, _), mask in zip(todo, pool.map(lambda np_: object_mask(np_[1], prompt), todo)):
            cache[(name, prompt)] = mask
    if todo:
        pickle.dump(cache, open(cache_path, "wb"))
    return {name: cache[(name, prompt)] for name, _ in prepared}


def scan(photo_paths, prompt, out_dir, step=0.75, progress=lambda *a: None, timings=None):
    import time
    timings = {} if timings is None else timings
    os.makedirs(out_dir, exist_ok=True)
    t = time.time(); progress("photos", f"{len(photo_paths)} photos")
    prepared = photos.prepare(photo_paths, os.path.join(out_dir, "photos"))
    timings["photos"] = round(time.time() - t, 1); t = time.time(); progress("markers", "finding the sheet's markers")
    size = cv2.imread(prepared[0][1]).shape[1::-1]
    views, K, rms = markers.solve([(n, cv2.imread(full, cv2.IMREAD_GRAYSCALE), cv2.imread(p).shape[1::-1])
                                   for n, p, full in prepared])
    posed = {v["name"] for v in views}
    timings["markers"] = round(time.time() - t, 1); t = time.time()
    progress("masks", f"{len(views)} cameras placed; SAM 3.1 is cutting the object out")
    masks = masks_for([(n, p) for n, p, _ in prepared if n in posed], prompt, os.path.join(out_dir, "masks.pkl"))
    views = [v for v in views if masks.get(v["name"]) is not None]
    mask_list = [masks[v["name"]] for v in views]
    timings["masks"] = round(time.time() - t, 1); t = time.time(); progress("hull", "building the shape from the photos")
    mesh = visual_hull(views, mask_list, step=step)
    timings["hull"] = round(time.time() - t, 1)
    mesh.export(os.path.join(out_dir, "hull.stl"))
    agreement = {v["name"]: round(iou(silhouette(mesh, v, size), m), 3) for v, m in zip(views, mask_list)}
    report = {
        "photos": len(prepared), "posed": len(views),
        "skipped": sorted({n for n, _, _ in prepared} - {v["name"] for v in views}),
        "focal_px": round(float(K[0, 0]), 1), "calibration_rms_px": None if rms is None else round(rms, 3),
        "marker_error_px": {v["name"]: round(v["err_px"], 2) for v in views},
        "extents_mm": [round(float(x), 1) for x in mesh.bounds[1] - mesh.bounds[0]],
        "volume_cm3": round(float(mesh.volume) / 1000, 2), "agreement": agreement,
    }
    json.dump(report, open(os.path.join(out_dir, "report.json"), "w"), indent=1)
    pickle.dump({"views": [{k: v[k] for k in ("name", "rv", "tv", "K")} for v in views],
                 "masks": mask_list, "size": size}, open(os.path.join(out_dir, "views.pkl"), "wb"))
    return mesh, report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--step", type=float, default=0.75)
    ap.add_argument("photos", nargs="+")
    a = ap.parse_args()
    _, rep = scan(a.photos, a.prompt, a.out, a.step)
    print(json.dumps(rep, indent=1))
