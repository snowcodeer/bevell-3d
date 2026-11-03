"""CAD for every benchmark object: STEP model, parametric STEP holder, top-view DXF, scored.

    .venv/bin/python -m tools.cad_bench
"""
import json, os, time
import cadquery as cq, trimesh
from bevell3d.cad import to_cad, holder_cad_safe, to_mesh, write_dxf
from bevell3d.run import HULL_HOLDER_AGREEMENT
from tools.bench_eval import truth_mesh, surface_distance, holder_fit, crop_to

OBJECTS = [("mario", None), ("mug", None), ("bottle", None), ("tape", None), ("mouse", 4)]


def main():
    rows = []
    for name, crop in OBJECTS:
        d = f"out/bench/{name}/full"
        t0 = time.time()
        summary = json.load(open(f"{d}/summary.json"))
        model = trimesh.load(f"{d}/model.stl")
        hull = trimesh.load(f"{d}/hull.stl")
        solid, kind, info, why = to_cad(model, summary["plan"]["route"])
        cq.exporters.export(cq.Workplane().add(solid), f"{d}/model.step")
        cad_mesh = to_mesh(solid); cad_mesh.export(f"{d}/model_cad.stl")
        base = hull if summary["hull_agreement"] >= HULL_HOLDER_AGREEMENT else model
        h, hinfo, pocket, outer = holder_cad_safe(base)
        cq.exporters.export(cq.Workplane().add(h), f"{d}/holder.step")
        hmesh = to_mesh(h); hmesh.export(f"{d}/holder_cad.stl")
        write_dxf(f"{d}/holder_top.dxf", pocket, outer)
        truth = truth_mesh(json.load(open(f"out/bench/{name}/truth.json")))
        if crop:
            truth = crop_to(truth, model, crop)
        sd = surface_distance(truth, cad_mesh)
        fit = holder_fit(hmesh, truth)
        row = {"name": name, "cad_kind": kind, "cad_info": {k: v for k, v in info.items() if not isinstance(v, dict)},
               "why_not": {k: str(v)[:120] for k, v in why.items()},
               "cad_mm": [round(float(e), 1) for e in cad_mesh.extents],
               "cad_surface_mean": round(sd["truth_to_model_mean"], 2), "cad_surface_p90": round(sd["truth_to_model_p90"], 2),
               "holder_cut_round": "hull" if base is hull else summary["model_source"],
               "holder": {k: round(v, 4) for k, v in fit.items()}, "holder_params": hinfo,
               "step_kb": round(os.path.getsize(f"{d}/model.step") / 1024), "holder_step_kb": round(os.path.getsize(f"{d}/holder.step") / 1024),
               "seconds": round(time.time() - t0, 1)}
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("name", "cad_kind", "cad_mm", "cad_surface_mean", "holder", "seconds")}, default=float), flush=True)
    json.dump(rows, open("out/results/cad.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
