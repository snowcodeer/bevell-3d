"""End to end: build feature trees in the open Fusion 360 (through BevellBridge) and in CadQuery,
and check that they agree.

    .venv/bin/python -m tools.fusion_e2e            # every tree below
    .venv/bin/python -m tools.fusion_e2e --keep     # leave the designs open in Fusion

A tree passes when Fusion builds every step and its body matches CadQuery's to within 3% in
volume and 0.5 mm in size.
"""
import argparse, json, sys, time
import requests
from bevell3d.feature_tree import validate, to_cadquery, to_fusion_script
from tests.test_feature_tree import BOTTLE, MUG

BRIDGE = "http://127.0.0.1:47822"

LOFT_CUT = {
    "parameters": [{"name": "w", "value": 60, "min": 30, "max": 90, "what": "base width"},
                   {"name": "top_d", "value": 30, "min": 10, "max": 50, "what": "top diameter"},
                   {"name": "h", "value": 40, "min": 20, "max": 60, "what": "height"},
                   {"name": "hole", "value": 12, "min": 4, "max": 20, "what": "hole diameter"}],
    "steps": [{"id": "body", "op": "loft", "sections": [{"z": 0, "shape": {"rect": {"w": "w", "l": "w*0.7"}}},
                                                       {"z": "h", "shape": {"circle": {"d": "top_d"}}}]},
              {"id": "bore", "op": "extrude", "shape": {"circle": {"d": "hole"}}, "from_z": 0, "height": "h", "mode": "cut"},
              {"id": "foot", "op": "chamfer", "edges": "bottom", "size": 1.5}],
}
BLOCK = {
    "parameters": [{"name": "l", "value": 70, "min": 40, "max": 100, "what": "length"},
                   {"name": "b", "value": 40, "min": 20, "max": 60, "what": "breadth"},
                   {"name": "t", "value": 15, "min": 5, "max": 30, "what": "thickness"},
                   {"name": "r", "value": 4, "min": 1, "max": 8, "what": "corner round"}],
    "steps": [{"id": "plate", "op": "extrude", "shape": {"rect": {"w": "l", "l": "b"}}, "height": "t"},
              {"id": "boss", "op": "extrude", "shape": {"ellipse": {"w": "l*0.5", "l": "b*0.5"}}, "from_z": "t", "height": "t*0.6"},
              {"id": "notch", "op": "extrude", "shape": {"polygon": [["l/2 - 12", -6], ["l/2", -6], ["l/2", 6], ["l/2 - 12", 6]]}, "height": "t", "mode": "cut"},
              {"id": "corners", "op": "fillet", "edges": "vertical", "radius": "r"}],
}


def cases():
    out = [("bottle (hand-written)", BOTTLE), ("mug (hand-written)", MUG), ("loft, cut, chamfer", LOFT_CUT), ("block, ellipse, polygon cut, fillet", BLOCK)]
    for name, path in (("bottle (Muse Spark)", "out/bench/bottle/timed/agent_tree.json"), ("mouse (Muse Spark)", "out/bench/mouse/full/agent_tree.json")):
        try:
            out.append((name, json.load(open(path))))
        except FileNotFoundError:
            pass
    return out


def cadquery_report(tree, p):
    shape, warns = to_cadquery(tree, p)
    bb = shape.BoundingBox()
    import trimesh, numpy as np
    vs, fs = shape.tessellate(0.05, 0.2)
    m = trimesh.Trimesh(np.array([v.toTuple() for v in vs]), np.array(fs))
    return {"volume_mm3": shape.Volume(), "size_mm": [round(float(e), 2) for e in m.extents], "warnings": warns}


def main(keep=False):
    try:
        requests.get(BRIDGE, timeout=3).raise_for_status()
    except Exception:
        sys.exit("BevellBridge is not running in Fusion: Utilities > Add-Ins > Scripts and Add-Ins > Add-Ins > BevellBridge > Run")
    rows = []
    for name, tree in cases():
        validate(tree)
        p = {q["name"]: q["value"] for q in tree["parameters"]}
        t = time.time()
        fusion = requests.post(BRIDGE + "/build", json={"script": to_fusion_script(tree, p, name), "close": not keep}, timeout=320).json()
        cq = cadquery_report(tree, p)
        ok, why = True, []
        if fusion.get("fatal"):
            ok, why = False, ["fatal: " + fusion["fatal"].strip().splitlines()[-1]]
        if fusion.get("errors"):
            ok = False; why += [e.strip().splitlines()[0] + " / " + e.strip().splitlines()[-1] for e in fusion["errors"]]
        bodies = [b for b in fusion.get("bodies", []) if b.get("solid", True)]
        if not bodies:
            ok = False; why.append("no solid body")
        else:
            fv = sum(b["volume_mm3"] for b in bodies)
            fs = bodies[0]["size_mm"]
            dv = fv / cq["volume_mm3"] - 1
            ds = max(abs(sorted(fs)[i] - sorted(cq["size_mm"])[i]) for i in range(3))
            if abs(dv) > 0.03 or ds > 0.5:
                ok = False
            why.append(f"volume {fv / 1000:.1f} vs {cq['volume_mm3'] / 1000:.1f} cm3 ({dv * 100:+.1f}%), size off {ds:.2f} mm, {len(bodies)} body")
        rows.append({"case": name, "ok": ok, "timeline": fusion.get("timeline"), "parameters": len(fusion.get("parameters", {})), "notes": why,
                     "seconds": round(time.time() - t, 1)})
        print(("PASS " if ok else "FAIL ") + name.ljust(38), " | ".join(why), f"({rows[-1]['seconds']} s)", flush=True)
    json.dump(rows, open("out/fusion_e2e.json", "w"), indent=1)
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--keep", action="store_true")
    main(ap.parse_args().keep)
