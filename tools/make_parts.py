"""Designed test parts with exact CAD, for checking the prismatic route and the edge cases.

Each is written as out/bench/parts/<name>/meshes/model.obj in metres, base at z = 0, the way
the scanned objects are, plus truth.step, so tools/render_bench.py photographs it and
tools/bench_eval.py scores against it.

    .venv/bin/python -m tools.make_parts
"""
import math, os
import cadquery as cq
import numpy as np, trimesh

OUT = "out/bench/parts"


def bracket():
    """Two extrusion levels and three through holes: a base plate with a raised boss."""
    base = cq.Workplane("XY").rect(90, 60).extrude(8).edges("|Z").fillet(6)
    boss = cq.Workplane("XY").workplane(offset=8).center(10, 0).rect(40, 30).extrude(22)
    part = base.union(boss)
    part = part.faces(">Z").workplane().center(10, 0).hole(12)
    return part.faces("<Z").workplane().pushPoints([(-32, -18), (-32, 18)]).hole(8)


def l_bracket():
    """An L standing up: slices are the whole base, then the upright leg."""
    return cq.Workplane("XZ").polyline([(0, 0), (80, 0), (80, 8), (8, 8), (8, 50), (0, 50)]).close().extrude(-40) \
        .faces(">X").workplane().pushPoints([(-12, 4)]).hole(6, 10)


def gear(teeth=14, od=72.0, root=60.0, thick=14.0):
    """A spur gear with a hub on top and a bore: a busy outline and two levels."""
    pts = []
    for k in range(teeth):
        a0 = 2 * math.pi * k / teeth
        for frac, r in ((0.0, root / 2), (0.15, od / 2), (0.45, od / 2), (0.6, root / 2)):
            a = a0 + frac * 2 * math.pi / teeth
            pts.append((r * math.cos(a), r * math.sin(a)))
    body = cq.Workplane("XY").polyline(pts).close().extrude(thick)
    hub = cq.Workplane("XY").workplane(offset=thick).circle(14).extrude(10)
    return body.union(hub).faces(">Z").workplane().hole(10)


def wedge_stand():
    """A phone stand with a sloped face: not prismatic, so the route must say no."""
    return cq.Workplane("XZ").polyline([(0, 0), (70, 0), (70, 10), (20, 60), (0, 60)]).close().extrude(-60)


PARTS = {"bracket": (bracket, "0.80,0.25,0.15"), "l_bracket": (l_bracket, "0.15,0.35,0.75"),
         "gear": (gear, "0.85,0.55,0.10"), "wedge_stand": (wedge_stand, "0.20,0.55,0.30")}


def main():
    for name, (make, colour) in PARTS.items():
        d = os.path.join(OUT, name, "meshes"); os.makedirs(d, exist_ok=True)
        solid = make().val()
        bb = solid.BoundingBox()
        solid = solid.translate(cq.Vector(-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -bb.zmin))
        cq.exporters.export(cq.Workplane().add(solid), os.path.join(OUT, name, "truth.step"))
        vs, fs = solid.tessellate(0.02, 0.1)
        m = trimesh.Trimesh(np.array([v.toTuple() for v in vs]) / 1000.0, np.array(fs))
        m.export(os.path.join(d, "model.obj"))
        open(os.path.join(OUT, name, "colour.txt"), "w").write(colour)
        print(name, [round(e * 1000, 1) for e in m.extents], "mm,", round(solid.Volume() / 1000, 1), "cm3")


if __name__ == "__main__":
    main()
