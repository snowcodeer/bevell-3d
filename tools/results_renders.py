"""Renders and numbers for the results page: each benchmark object's truth beside our model
(and SAM 3D's fit), and the true object seated in the holder made for it.

    .venv/bin/python -m tools.results_renders
"""
import json, os, subprocess
import numpy as np, trimesh
from PIL import Image
from tools.bench_eval import truth_mesh, crop_to

BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
OUT = "out/results"
OBJECTS = [("mario", None), ("mug", None), ("bottle", None), ("tape", None), ("mouse", 4)]
TRUTH, OURS, SAM3D, HOLDER, SEATED, CAD = "c9c4bb", "395af6", "8f74d6", "e6e6ea", "f08a4b", "8c97a6"


def small(m, faces=80000):
    return m.simplify_quadric_decimation(face_count=faces) if len(m.faces) > faces else m


def blender(parts, out_png, res="2200x1240", elevation=30):
    tmp = []
    args = [BLENDER, "-b", "-P", "tools/blender_render.py", "--", "--out", out_png, "--res", res,
            "--samples", "24", "--elevation", str(elevation)]
    for k, (mesh, col) in enumerate(parts):
        p = os.path.join(OUT, f"_part{k}.stl"); small(mesh).export(p); tmp.append(p)
        args += ["--part", f"{p}:{col}"]
    subprocess.run(args, check=True, capture_output=True)
    for p in tmp:
        os.remove(p)
    jpg = out_png.replace(".png", ".jpg")
    Image.open(out_png).convert("RGB").save(jpg, quality=86); os.remove(out_png)
    return os.path.basename(jpg)


def side_by_side(meshes, gap=18.0):
    """Lay meshes out left to right on the floor, each resting at z = 0."""
    out, x = [], 0.0
    for m, col in meshes:
        m = m.copy(); lo, hi = m.bounds
        m.apply_translation((x - lo[0], -(lo[1] + hi[1]) / 2, -lo[2]))
        out.append((m, col)); x += (hi[0] - lo[0]) + gap
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    data = []
    for name, crop in OBJECTS:
        d = f"out/bench/{name}"
        t = json.load(open(f"{d}/truth.json"))
        truth = truth_mesh(t)
        model = trimesh.load(f"{d}/full/model.stl")
        if crop:
            truth = crop_to(truth, model, crop)
        hull = trimesh.load(f"{d}/full/hull.stl")
        holder = trimesh.load(f"{d}/full/holder_cad.stl" if os.path.exists(f"{d}/full/holder_cad.stl") else f"{d}/full/holder.stl")
        summary = json.load(open(f"{d}/full/summary.json"))
        score = json.load(open(f"{d}/full/{'score_cropped' if crop else 'score'}.json"))
        row = [(truth, TRUTH), (hull, OURS)]
        s3 = f"{d}/full/sam3d_fitted.stl"
        if os.path.exists(s3):
            row.append((trimesh.load(s3), SAM3D))
        compare = blender(side_by_side(row), os.path.join(OUT, f"{name}_compare.png"))
        seated = truth.copy(); seated.apply_translation((0, 0, 2.0 - truth.bounds[0][2]))
        fit = blender([(holder, HOLDER), (seated, SEATED)], os.path.join(OUT, f"{name}_holder.png"), elevation=38)
        cad_img = None
        if os.path.exists(f"{d}/full/model_cad.stl"):
            cad_img = blender([(trimesh.load(f"{d}/full/model_cad.stl"), CAD)], os.path.join(OUT, f"{name}_cad.png"))
        photo = f"{name}_photo.jpg"
        Image.open(f"{d}/photos/IMG_03.jpg").convert("RGB").resize((672, 504), Image.LANCZOS).save(os.path.join(OUT, photo), quality=82)
        sd = lambda k: round(score[k]["truth_to_model_mean"], 2)
        data.append({
            "name": name, "prompt": summary["plan"]["object"], "route": summary["plan"]["route"],
            "reason": summary["plan"]["reason"], "issues": summary["plan"]["photo_issues"],
            "model_source": summary["model_source"],
            "true_mm": score["true_mm"], "hull_mm": score["hull_mm"],
            "sam3d_mm": summary.get("sam3d", {}).get("extents_mm"),
            "cameras": score["cameras"], "focal_px": summary["scan"]["focal_px"],
            "hull_surface_mean": round(score["hull_surface_mm"]["truth_to_model_mean"], 2),
            "hull_surface_p90": round(score["hull_surface_mm"]["truth_to_model_p90"], 2),
            "agreement": {k: round(v, 3) for k, v in score["agreement"].items()},
            "holder": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in score["holder_fit"].items()},
            "holder_mm": summary["holder"]["holder_mm"],
            "images": {"photo": photo, "compare": compare, "holder": fit, "cad": cad_img}, "cropped": crop,
        })
        print("rendered", name)
    json.dump(data, open(os.path.join(OUT, "results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
