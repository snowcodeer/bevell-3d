"""Copy benchmark results into the web app as worked examples (out/scans/example-<name>/).

    .venv/bin/python -m tools.seed_examples
"""
import json, os, shutil, time
import trimesh

SCANS = "out/scans"
TITLES = {"mario": "Mario figure", "bottle": "Vitamin bottle", "tape": "Tape roll", "mug": "Mug", "mouse": "White mouse",
          "clock": "Alarm clock", "camera": "Camera lens", "bracket": "Bracket", "gear": "Gear", "fish": "Fish toothbrush holder", "servo": "Hobby servo"}
# What the start screen shows: one of each kind (round, prismatic, freeform) and the robot part.
SHOWN = ("servo", "bottle", "bracket", "gear", "mug", "clock", "mario", "fish", "tape")


def rebuild_holder(out, summary):
    """Cut the example's holder with today's holder_cad, so the examples show the current design."""
    import cadquery as cq
    from bevell3d.cad import holder_cad_safe, to_mesh, write_dxf
    from bevell3d.run import HULL_HOLDER_AGREEMENT
    hull = summary.get("hull_agreement", 0) >= HULL_HOLDER_AGREEMENT
    base = trimesh.load(f"{out}/{'hull' if hull else 'model'}.stl")
    solid, info, pocket, outer = holder_cad_safe(base)
    cq.exporters.export(cq.Workplane().add(solid), f"{out}/holder.step")
    write_dxf(f"{out}/holder_top.dxf", pocket, outer)
    mesh = to_mesh(solid)
    mesh.export(f"{out}/holder.stl"); mesh.export(f"{out}/holder.3mf")
    return {**info, "cut_round": "hull" if hull else summary.get("model_source")}


def seed(name):
    # The run to show: timed (a clean timing run), else closer (redone with the closer look), else full.
    src = next((f"out/bench/{name}/{t}" for t in ("timed", "closer") if os.path.exists(f"out/bench/{name}/{t}/summary.json")),
               f"out/bench/{name}/full")
    dst = f"{SCANS}/example-{name}"
    shutil.rmtree(dst, ignore_errors=True); os.makedirs(f"{dst}/result")
    summary = json.load(open(f"{src}/summary.json"))
    copies = {"views.pkl": "views.pkl", "hull.stl": "hull.stl", "agent_model.step": "agent_model.step",
              "agent_model.py": "agent_model.py", "agent_tree.json": "agent_tree.json", "agent_fusion.zip": "agent_fusion.zip", "agent_model.stl": "agent_model.stl", "agent_report.json": "agent_report.json",
              "model.stl": "model.stl", "model_cad.stl": "model_cad.stl", "model.step": "model.step", "holder.step": "holder.step",
              "model_tree.json": "model_tree.json", "model_fusion.zip": "model_fusion.zip",
              "holder_top.dxf": "holder_top.dxf", "plan.json": "plan.json"}
    if "cad" not in summary:                          # made before the CAD holder was the default
        cad = {c["name"]: c for c in json.load(open("out/results/cad.json"))}[name]
        copies.update({"holder_cad.stl": "holder.stl", "holder.stl": "holder_nest.stl"})
        summary["cad"] = {"kind": cad["cad_kind"], "info": cad["cad_info"]}
        summary["holder"] = {**cad["holder_params"], "floor_mm": cad["holder_params"]["floor"]}
    else:
        copies.update({"holder.stl": "holder.stl", "holder_nest.stl": "holder_nest.stl", "holder.3mf": "holder.3mf"})
    # The CAD agent's best run: the richer brief (rich/), else tree mode (tree/), else the shown
    # run's own, else the full run's (a rerun with the closer look has no agent run of its own).
    agent_src = next((d for d in (f"out/bench/{name}/rich", f"out/bench/{name}/tree", src, f"out/bench/{name}/full")
                      if os.path.exists(f"{d}/agent_tree.json")), src)
    for a, b in copies.items():
        here = agent_src if a.startswith("agent_") else src
        if a.startswith("agent_") and here != src and not os.path.exists(f"{here}/{a}"):
            continue                                  # a tree run has no CadQuery script; do not mix runs
        if os.path.exists(f"{here}/{a}"):
            shutil.copy(f"{here}/{a}", f"{dst}/result/{b}")
    if not os.path.exists(f"{src}/pads.3mf"):          # scans made before pads were part of a run
        from bevell3d.gripper import write_pads
        try:
            _, g = write_pads(f"{dst}/result", trimesh.load(f"{dst}/result/model.stl"))
            summary["grasp"] = {k: g[k] for k in ("centre_mm", "squeeze_axis", "closed_on_object_mm")}
        except Exception as e:
            print("no pads for", name, e)
    else:
        for f in ("pads.3mf", "pad_fixed_jaw.stl", "pad_moving_jaw.stl", "grasp.json"):
            shutil.copy(f"{src}/{f}", f"{dst}/result/{f}")
    if os.path.isdir(f"{src}/photos"):                # the agent checks its CAD against these
        shutil.copytree(f"{src}/photos", f"{dst}/result/photos", ignore=shutil.ignore_patterns("full"))
    summary["holder"] = rebuild_holder(f"{dst}/result", summary)
    try:                                                 # the robot fixture, as today's runner makes it
        from bevell3d.fixture import write_fixture
        fx = write_fixture(f"{dst}/result", trimesh.load(f"{dst}/result/model.stl"))
        summary["fixture"] = {"tag_id": fx["tag"]["id"], "grasp_mm": fx["grasp"]["centre_mm"], "relief_mm": fx["fixture"]["relief_mm"]}
    except Exception as e:
        print("no fixture for", name, e)
    if summary.get("cad", {}).get("kind") == "mesh":     # freeform: today's smooth NURBS STEP
        import cadquery as cq
        from bevell3d.nurbs import scan_to_nurbs
        from bevell3d.cad import to_mesh
        try:
            solid, rep = scan_to_nurbs(f"{dst}/result/model.stl", f"{dst}/result/model.step")
            to_mesh(solid).export(f"{dst}/result/model_cad.stl")
            summary["cad"] = {"kind": "nurbs", "info": {k: v for k, v in rep.items() if k != "retries"}}
        except Exception as e:
            print("no NURBS for", name, e)
    if os.path.exists(f"{dst}/result/agent_tree.json"):   # today's Fusion script, not the one the run wrote
        from bevell3d.feature_tree import write_fusion_zip
        tree = json.load(open(f"{dst}/result/agent_tree.json"))
        write_fusion_zip(f"{dst}/result", tree, f"{summary['plan']['object']}: {tree.get('features', '')}")
    summary["holder"].setdefault("floor_mm", summary["holder"].get("floor", 2.0))
    agent = None
    if os.path.exists(f"{dst}/result/agent_report.json"):
        agent = {"state": "done", "report": json.load(open(f"{dst}/result/agent_report.json"))}
    st = {"state": "done", "stage": "done", "title": TITLES[name], "summary": summary, "plan": summary["plan"], "agent": agent,
          "elapsed": summary.get("timings_s", {}).get("total"), "done": [], "created": time.time()}
    json.dump(st, open(f"{dst}/status.json", "w"), default=float)
    print("seeded", dst, "from", src)


if __name__ == "__main__":
    import sys
    for n in sys.argv[1:] or SHOWN:
        seed(n)
