"""Every benchmark object against its true shape, in one table (out/results/bench_table.json).

    .venv/bin/python -m tools.bench_table
"""
import json, os, sys
import numpy as np, trimesh
from tools.bench_eval import truth_mesh, surface_distance, holder_fit, crop_to

CASES = [("bottle", "timed", None), ("tape", "full", None), ("mug", "full", None), ("mario", "timed", None), ("mouse", "full", 4),
         ("clock", "full", None), ("camera", "full", None), ("bracket", "full", None), ("l_bracket", "full", None),
         ("gear", "full", None), ("wedge_stand", "full", None), ("letters", "joined", None), ("fish", "full", None), ("android", "full", None)]


def row(name, tag, crop):
    d = f"out/bench/{name}/{tag}"
    s = json.load(open(f"{d}/summary.json"))
    truth = truth_mesh(json.load(open(f"out/bench/{name}/truth.json")))
    model = trimesh.load(f"{d}/model.stl")
    if crop:
        truth = crop_to(truth, model, crop)
    true_mm = sorted(float(e) for e in truth.extents); ours = sorted(s["model_mm"])
    r = {"object": name, "named": s["plan"]["object"], "route": s["plan"]["route"], "source": s.get("model_source"),
         "posed": f"{s['scan']['posed']}/{s['scan']['photos']}" if "scan" in s else None,
         "true_mm": [round(v, 1) for v in true_mm], "model_mm": ours, "size_off_mm": round(max(abs(a - b) for a, b in zip(ours, true_mm)), 1),
         "surface_mm": round(surface_distance(truth, model)["truth_to_model_mean"], 2), "cad": s.get("cad", {}).get("kind")}
    if os.path.exists(f"{d}/model_cad.stl"):
        r["cad_surface_mm"] = round(surface_distance(truth, trimesh.load(f"{d}/model_cad.stl"))["truth_to_model_mean"], 2)
    for f in ("holder.stl",):
        if os.path.exists(f"{d}/{f}"):
            fit = holder_fit(trimesh.load(f"{d}/{f}"), truth)
            r["holder_catch_mm"] = round(fit["max_penetration_mm"], 2)
    for agent_dir in (f"out/bench/{name}/rich", f"out/bench/{name}/tree", d):
        if os.path.exists(f"{agent_dir}/agent_model.stl"):
            r["agent_surface_mm"] = round(surface_distance(truth, trimesh.load(f"{agent_dir}/agent_model.stl"))["truth_to_model_mean"], 2)
            r["agent_features"] = json.load(open(f"{agent_dir}/agent_report.json")).get("features")
            break
    return r


def main():
    rows = []
    for name, tag, crop in CASES:
        try:
            rows.append(row(name, tag, crop))
            print(json.dumps(rows[-1]), flush=True)
        except Exception as e:
            print(name, "skipped:", type(e).__name__, e, flush=True)
    os.makedirs("out/results", exist_ok=True)
    json.dump(rows, open("out/results/bench_table.json", "w"), indent=1)


if __name__ == "__main__":
    main()
