"""The whole flow: photos on the capture sheet in; a true-size model and a holder out.

    python -m bevell3d.run --out out/airpods photos/IMG_*.HEIC

1. Muse Spark plans: what to ask SAM 3.1 for, and the route.
2. Markers give every camera and the lens; SAM 3.1 cuts the object out of every photo;
   the visual hull is the measured outer bound.
3. A revolved object (bottle, cup) is rebuilt from its radius profile. For a freeform one, SAM 3D Objects (on Modal) generates the shape from the best photo
   and `fit` puts it at true size against every photo. It is kept only if it agrees with
   the photos at least as well as the hull does, less a small margin.
4. The model is written as CAD (STEP: a revolve or loft where it can be, else a sewn mesh
   solid) and a parametric holder is cut for it (STEP, STL and a top-view DXF), with the
   underside-following nest kept as an alternative.
"""
import argparse, glob, io, json, os, pickle
import numpy as np, cv2, trimesh
from PIL import Image
from . import planner, photos
from .scan import scan
from .fit import fit
from .holder import make_holder, seated
from .revolve import revolved
from .project import silhouette, iou
from .render import render, render_scene

# The hull is cut from the masks, so it always matches them best; a generated shape that
# agrees a little less is often nearer the real surface. On the 3 Nov benchmark (rendered
# Google Scanned Objects) SAM 3D was nearer on the mug (2.98 vs 3.57 mm mean) at 0.074 less
# agreement and on the mouse, and further on Mario at 0.117 less. Tuned on three objects.
KEEP_MARGIN = 0.08
# Masks that agree with each other this well make the hull a trustworthy outer bound, and the
# holder is cut round it: on the benchmark it fitted every such object (worst catch 1.2 mm
# on 2% of the tape's surface). Below this, the holder follows the chosen model.
HULL_HOLDER_AGREEMENT = 0.95


def camera_elevation(view, target):
    R, _ = cv2.Rodrigues(view["rv"])
    c = (-R.T @ view["tv"]).ravel()
    d = c - target
    return float(np.degrees(np.arctan2(d[2], np.hypot(d[0], d[1]))))


def best_photo(views, masks, target):
    """The photo SAM 3D sees best: 25 to 60 degrees up, with the largest outline."""
    scored = []
    for v, m in zip(views, masks):
        e = camera_elevation(v, target)
        scored.append(((25 <= e <= 60), int(m.sum()), v["name"]))
    return max(scored)[2]


def sam3d_mesh(photo_path, mask):
    import modal
    Sam3D = modal.Cls.from_name("bevell-sam3d", "Sam3D")
    buf = io.BytesIO(); Image.fromarray(mask.astype(np.uint8) * 255).save(buf, "PNG")
    res = Sam3D().reconstruct.remote(open(photo_path, "rb").read(), buf.getvalue())
    scene = trimesh.load(io.BytesIO(res["glb"]), file_type="glb")
    mesh = scene.dump(concatenate=True) if isinstance(scene, trimesh.Scene) else scene
    return mesh, res["pose"]


def agreement(mesh, views, masks, size):
    return float(np.mean([iou(silhouette(mesh, v, size), m) for v, m in zip(views, masks)]))


def run(photo_paths, out_dir, prompt=None, use_sam3d=True, log=print, progress=lambda stage, detail="": None):
    import time
    os.makedirs(out_dir, exist_ok=True)
    timings, t0, t = {}, time.time(), time.time()
    progress("plan", "Muse Spark is looking at the photos")
    plan = planner.plan(photo_paths) if prompt is None else {"object": prompt, "route": "freeform", "reason": "given", "photo_issues": []}
    timings["plan"] = round(time.time() - t, 1)
    json.dump(plan, open(os.path.join(out_dir, "plan.json"), "w"), indent=1)
    log(f"plan: {plan['object']!r}, {plan['route']}; issues: {plan['photo_issues']}")
    hull, rep = scan(photo_paths, plan["object"], out_dir, progress=progress, timings=timings)
    log(f"hull: {rep['extents_mm']} mm from {rep['posed']}/{rep['photos']} photos, focal {rep['focal_px']} px")
    vp = pickle.load(open(os.path.join(out_dir, "views.pkl"), "rb"))
    views, masks, size = vp["views"], vp["masks"], vp["size"]
    summary = {"plan": plan, "scan": rep, "hull_agreement": agreement(hull, views, masks, size)}
    final, source = hull, "hull"
    if plan["route"] == "revolved":
        t = time.time(); progress("revolve", "rebuilding it as a turned profile")
        rev, rrep = revolved(views, masks)
        timings["revolve"] = round(time.time() - t, 1)
        rrep["agreement"] = agreement(rev, views, masks, size)
        summary["revolved"] = rrep
        log(f"revolved: height {rrep['height_mm']} mm, widest {rrep['max_diameter_mm']} mm, agreement {rrep['agreement']:.3f}")
        if rrep["agreement"] >= summary["hull_agreement"] - KEEP_MARGIN:
            final, source = rev, "revolved"
    if use_sam3d and plan["route"] == "freeform":
        try:
            name = best_photo(views, masks, hull.bounding_box.centroid)
            i = [v["name"] for v in views].index(name)
            t = time.time(); progress("sam3d", "SAM 3D is generating the full shape")
            gen, pose = sam3d_mesh(os.path.join(out_dir, "photos", name + ".jpg"), masks[i])
            timings["sam3d"] = round(time.time() - t, 1); t = time.time(); progress("fit", "sizing SAM 3D's shape against every photo")
            gen.export(os.path.join(out_dir, "sam3d_raw.glb"))
            fitted, frep = fit(gen, views, masks, size, guide=hull, log=log)
            timings["fit"] = round(time.time() - t, 1)
            fitted.export(os.path.join(out_dir, "sam3d_fitted.stl"))
            frep["agreement"] = agreement(fitted, views, masks, size)
            frep["photo"] = name
            summary["sam3d"] = frep
            log(f"SAM 3D from {name}: {frep['extents_mm']} mm, agreement {frep['agreement']:.3f} vs hull {summary['hull_agreement']:.3f}")
            if frep["agreement"] >= summary["hull_agreement"] - KEEP_MARGIN:
                final, source = fitted, "sam3d"
        except Exception as e:                       # the hull still stands; say why
            summary["sam3d_error"] = f"{type(e).__name__}: {e}"
            log("SAM 3D skipped:", summary["sam3d_error"])
    final.export(os.path.join(out_dir, "model.stl"))
    holder_base = hull if summary["hull_agreement"] >= HULL_HOLDER_AGREEMENT else final
    # The nest follows the object's underside, on a voxel grid; kept as an alternative print.
    t = time.time(); progress("cad", "writing CAD and cutting the holder")
    nest, nrep = make_holder(holder_base)
    nest.export(os.path.join(out_dir, "holder_nest.stl"))
    summary["nest"] = nrep
    # CAD: the model as STEP (a revolve or loft where it can be, else its mesh sewn into a
    # solid) and the parametric holder as STEP, its STL and a top-view DXF. The CAD holder
    # fitted the benchmark better than the nest (mouse: 1.6 mm worst catch against 5.7 mm).
    holder = nest
    try:
        import cadquery as cq
        from .cad import to_cad, holder_cad_safe, to_mesh, write_dxf
        solid, kind, info, why = to_cad(final, plan["route"])
        cq.exporters.export(cq.Workplane().add(solid), os.path.join(out_dir, "model.step"))
        to_mesh(solid).export(os.path.join(out_dir, "model_cad.stl"))   # what the viewer shows
        summary["cad"] = {"kind": kind, "info": {k: v for k, v in info.items() if not isinstance(v, dict)},
                          "why_not": {k: str(v)[:160] for k, v in why.items()}}
        h, hrep, pocket, outer = holder_cad_safe(holder_base)
        cq.exporters.export(cq.Workplane().add(h), os.path.join(out_dir, "holder.step"))
        write_dxf(os.path.join(out_dir, "holder_top.dxf"), pocket, outer)
        holder = to_mesh(h)
        log(f"CAD: model as {kind}; holder {hrep['holder_mm']} mm")
    except Exception as e:                           # the meshes still stand; say why
        summary["cad_error"] = f"{type(e).__name__}: {e}"
        hrep = nrep
        log("CAD skipped:", summary["cad_error"])
    hrep["cut_round"] = "hull" if holder_base is hull else source
    holder.export(os.path.join(out_dir, "holder.stl"))
    # Bambu Studio opens a 3MF from a link, not an STL: the holder, ready to slice.
    try:
        holder.export(os.path.join(out_dir, "holder.3mf"))
    except Exception as e:                           # a missing 3MF must not lose the scan
        summary["threemf_error"] = f"{type(e).__name__}: {e}"
    timings["cad_and_holder"] = round(time.time() - t, 1)
    # Gripper pads for a robot to hold the object by its own shape (SO-101 jaws by default).
    try:
        from .gripper import write_pads
        _, grasp = write_pads(out_dir, final)
        summary["grasp"] = {k: grasp[k] for k in ("centre_mm", "squeeze_axis", "closed_on_object_mm")}
    except Exception as e:
        summary["pads_error"] = f"{type(e).__name__}: {e}"
    timings["total"] = round(time.time() - t0, 1)
    summary["timings_s"] = timings
    progress("done", "ready")
    summary.update(model_source=source, model_mm=[round(float(e), 1) for e in final.bounds[1] - final.bounds[0]], holder=hrep)
    render(final, os.path.join(out_dir, "model.png"), f"{plan['object']} ({source})")
    render_scene([(holder, (0.85, 0.85, 0.88)), (seated(final), (0.22, 0.35, 0.95))],
                 os.path.join(out_dir, "holder.png"), f"Holder for the {plan['object']}")
    json.dump(summary, open(os.path.join(out_dir, "summary.json"), "w"), indent=1, default=float)
    log(f"done: model from {source}, {summary['model_mm']} mm; holder {hrep['holder_mm']} mm -> {out_dir}")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prompt", help="skip the planner and ask SAM 3.1 for this")
    ap.add_argument("--no-sam3d", action="store_true")
    ap.add_argument("photos", nargs="+")
    a = ap.parse_args()
    paths = sorted(p for g in a.photos for p in glob.glob(g))
    run(paths, a.out, a.prompt, not a.no_sam3d)
