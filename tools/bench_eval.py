"""Run the whole pipeline on a rendered photo set and score it against the true object.

    .venv/bin/python -m tools.bench_eval out/bench/mario [--no-sam3d] [--prompt "..."]

Scores: recovered cameras against the renderer's; the model's size and surface distance
against the scanned mesh; and whether the real object fits the holder made for it.
"""
import argparse, glob, json, os, pickle
import numpy as np, cv2, trimesh
from scipy.spatial import cKDTree
from bevell3d.run import run


def truth_mesh(t):
    m = trimesh.load(t["obj"], force="mesh")
    m.apply_scale(1000.0)
    m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(t["yaw_deg"]), [0, 0, 1]))
    m.apply_translation((t["x_mm"], t["y_mm"], 0.0))
    return m


def surface_distance(a, b, n=20000):
    pa, pb = a.sample(n), b.sample(n)
    da, _ = cKDTree(pb).query(pa)          # truth -> model
    db, _ = cKDTree(pa).query(pb)          # model -> truth
    return {"truth_to_model_mean": float(da.mean()), "truth_to_model_p90": float(np.percentile(da, 90)),
            "model_to_truth_mean": float(db.mean()), "model_to_truth_p90": float(np.percentile(db, 90))}


def holder_fit(holder, truth, floor=2.0, n=12000):
    """Signed distance of the true surface, seated, into the holder: positive means it collides."""
    if len(holder.faces) > 60000:
        holder = holder.simplify_quadric_decimation(face_count=60000)
    seated = truth.copy(); seated.apply_translation((0, 0, floor - truth.bounds[0][2]))
    pts = seated.sample(n)
    d = trimesh.proximity.ProximityQuery(holder).signed_distance(pts)
    inside_pocket = pts[:, 2] < holder.bounds[1][2]
    gap = -d[inside_pocket]
    return {"max_penetration_mm": float(max(0.0, d.max())), "share_colliding_over_0.2mm": float((d > 0.2).mean()),
            "gap_below_rim_median_mm": float(np.median(gap[(gap > -5) & (gap < 5)])) if inside_pocket.any() else None}


def camera_error(out_dir, t):
    vp = pickle.load(open(os.path.join(out_dir, "views.pkl"), "rb"))
    true = {c["name"]: np.array(c["location_mm"]) for c in t["cameras"]}
    errs = []
    for v in vp["views"]:
        R, _ = cv2.Rodrigues(v["rv"]); c = (-R.T @ v["tv"]).ravel()
        errs.append(float(np.linalg.norm(c - true[v["name"]])))
    return {"posed": len(errs), "of": len(true), "median_mm": float(np.median(errs)), "max_mm": float(np.max(errs))}


def crop_to(truth, model, margin):
    """The part of the true object over the model's footprint (drops a cable SAM left out)."""
    lo, hi = model.bounds[0] - margin, model.bounds[1] + margin
    c = truth.triangles_center
    keep = np.all((c[:, :2] >= lo[:2]) & (c[:, :2] <= hi[:2]), axis=1)
    out = truth.copy(); out.update_faces(keep); out.remove_unreferenced_vertices()
    return out


def main(case, use_sam3d, prompt=None, tag="run", score_only=False, crop=None):
    t = json.load(open(os.path.join(case, "truth.json")))
    out = os.path.join(case, tag)
    photos = sorted(glob.glob(os.path.join(case, "photos", "*.jpg")))
    if score_only:
        summary = json.load(open(os.path.join(out, "summary.json")))
    else:
        summary = run(photos, out, prompt=prompt, use_sam3d=use_sam3d, log=lambda *a: print(os.path.basename(case), *a))
    truth = truth_mesh(t)
    model = trimesh.load(os.path.join(out, "model.stl"))
    hull = trimesh.load(os.path.join(out, "hull.stl"))
    holder = trimesh.load(os.path.join(out, "holder.stl"))
    if crop is not None:
        truth = crop_to(truth, model, crop)
    score = {
        "cropped_to_model_mm": crop,
        "object": os.path.basename(case), "route": summary["plan"]["route"], "sam_prompt": summary["plan"]["object"],
        "model_source": summary["model_source"],
        "true_mm": [round(float(e), 1) for e in truth.extents],
        "model_mm": [round(float(e), 1) for e in model.extents],
        "hull_mm": [round(float(e), 1) for e in hull.extents],
        "cameras": camera_error(out, t),
        "model_surface_mm": surface_distance(truth, model),
        "hull_surface_mm": surface_distance(truth, hull),
        "holder_fit": holder_fit(holder, truth),
        "agreement": {"hull": summary["hull_agreement"], **({"sam3d": summary["sam3d"]["agreement"]} if "sam3d" in summary else {}),
                      **({"revolved": summary["revolved"]["agreement"]} if "revolved" in summary else {})},
        "sam3d_error": summary.get("sam3d_error"),
    }
    json.dump(score, open(os.path.join(out, "score.json" if crop is None else "score_cropped.json"), "w"), indent=1, default=float)
    print(json.dumps(score, indent=1, default=float))
    return score


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--no-sam3d", action="store_true")
    ap.add_argument("--prompt")
    ap.add_argument("--tag", default="run")
    ap.add_argument("--score-only", action="store_true")
    ap.add_argument("--crop", type=float, help="score only the true surface over the model's footprint, plus this margin")
    a = ap.parse_args()
    main(a.case, not a.no_sam3d, a.prompt, a.tag, a.score_only, a.crop)
