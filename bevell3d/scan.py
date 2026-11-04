"""Photos on the capture sheet -> cameras -> SAM 3.1 masks -> visual hull at true scale.

    python -m bevell3d.scan --prompt "airpods case" --out out/airpods photos/IMG_*.HEIC
"""
import argparse, json, math, os, pickle
import numpy as np, cv2
from . import markers, photos
from .hull import visual_hull
from .project import silhouette, iou
from .sam_client import segment


def object_mask(path, prompt, min_conf=0.45):
    """The most confident SAM 3.1 instance for the prompt, joined by any other confident
    instance that touches it, as a full-size boolean mask.

    SAM 3.1 can return one object as several instances: on the letter holder it gave the red
    front compartments (0.83) and the dark back one (0.61) apart. Taking the first alone
    carved the back compartment out of the hull, 26 mm of height, because one photo's mask is
    enough to remove a part. An instance that does not touch the object (another thing on the
    sheet) stays out."""
    _, _, recs = segment(path, prompt, max_side=photos.MAX_SIDE)
    recs = sorted((r for r in recs if "mask" in r), key=lambda r: (r["conf"] or 0, r["mask"].sum()), reverse=True)
    if not recs:
        return None
    mask = recs[0]["mask"].copy()
    rest = [r for r in recs[1:] if (r["conf"] or 0) >= min_conf]
    k = max(3, int(0.01 * min(mask.shape)))
    grown = True
    while grown and rest:
        grown = False
        near = cv2.dilate(mask.astype(np.uint8), np.ones((2 * k + 1, 2 * k + 1), np.uint8)) > 0
        for r in list(rest):
            if (r["mask"] & near).sum() > 0.02 * max(r["mask"].sum(), 1):
                mask |= r["mask"]; rest.remove(r); grown = True
    return mask


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


def camera_centres(views):
    out = []
    for v in views:
        R, _ = cv2.Rodrigues(v["rv"])
        out.append((-R.T @ v["tv"]).ravel())
    return np.array(out)


def check_coverage(views, min_spread_deg=25.0):
    """Refuse a set of photos all taken from about the same place, before asking SAM for masks:
    sixteen copies of one photo gave a hull 243 mm deep that took minutes to process further."""
    if len(views) < 3:
        raise ValueError(f"Only {len(views)} photos show enough of the sheet's squares to place the camera. "
                         "Keep the whole sheet in view and take at least 8.")
    from .hull import AREA_LO, AREA_HI
    d = camera_centres(views) - (AREA_LO + AREA_HI) / 2 * np.array([1, 1, 0])
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    spread = math.degrees(math.acos(float(np.clip(np.min(d @ d.T), -1, 1))))
    if spread < min_spread_deg:
        raise ValueError(f"The photos were all taken from about the same spot (within {spread:.0f} degrees). "
                         "Take them from all the way round the object, as the guide shows.")


def check_bounded(mesh, margin=3.0):
    """A shape that reaches the edge of the white area is either not pinned down by the photos
    or hanging off the sheet; its size would be wrong either way, so say which."""
    from .hull import AREA_LO, AREA_HI
    lo, hi = mesh.bounds
    if hi[2] >= AREA_HI[2] - margin:
        raise ValueError("The shape isn't pinned down: it runs off the top. Take photos from more sides, "
                         "including two from above.")
    if (lo[:2] <= AREA_LO[:2] + margin).any() or (hi[:2] >= AREA_HI[:2] - margin).any():
        raise ValueError("The object reaches the sheet's squares, or the photos don't pin it down. Put it in the "
                         "middle of the white area, clear of the squares, and take photos from all the way round.")


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
    check_coverage(views)
    timings["markers"] = round(time.time() - t, 1); t = time.time()
    progress("masks", f"{len(views)} cameras placed; SAM 3.1 is cutting the object out")
    masks = masks_for([(n, p) for n, p, _ in prepared if n in posed], prompt, os.path.join(out_dir, "masks.pkl"))
    views = [v for v in views if masks.get(v["name"]) is not None]
    mask_list = [masks[v["name"]] for v in views]
    timings["masks"] = round(time.time() - t, 1); t = time.time(); progress("hull", "building the shape from the photos")
    mesh = visual_hull(views, mask_list, step=step)
    check_bounded(mesh)
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
