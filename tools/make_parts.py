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


def servo():
    """A hobby servo, the robot demo's part: case, mounting ears with four holes, output hub.

    Sized like an MG996R: a 40.7 x 19.7 mm case 37 mm tall, ears 54.5 mm across from 26.5 to
    29 mm up, holes 4.4 mm on 49.5 x 10 mm, a 13 mm hub to 42 mm off-centre over one end.
    """
    case = cq.Workplane("XY").rect(40.7, 19.7).extrude(37)
    ears = cq.Workplane("XY").workplane(offset=26.5).rect(54.5, 19.7).extrude(2.5) \
        .faces(">Z").workplane().pushPoints([(x, y) for x in (-24.75, 24.75) for y in (-5, 5)]).hole(4.4)
    hub = cq.Workplane("XY").workplane(offset=37).center(40.7 / 2 - 10, 0).circle(6.5).extrude(5)
    return case.union(ears).union(hub)


def sts3215():
    """A Feetech STS3215, the SO-101's own servo, as sold (horns loose in the bag): a black
    45.2 x 24.7 x 35 mm case standing on its base, a low boss with the brass output spline
    over one end of the top face, four screw heads in the top's corners, and the cable's
    strain relief out of the far end."""
    case = cq.Workplane("XY").rect(45.2, 24.7).extrude(35).edges("|Z").fillet(1.0)
    x = 45.2 / 2 - 11.5
    boss = cq.Workplane("XY").workplane(offset=35).center(x, 0).circle(5.5).extrude(1.5)
    spline = cq.Workplane("XY").workplane(offset=36.5).center(x, 0).circle(2.9).extrude(3.5)
    screws = cq.Workplane("XY").workplane(offset=35).pushPoints(
        [(sx * (45.2 / 2 - 2.6), sy * (24.7 / 2 - 2.6)) for sx in (-1, 1) for sy in (-1, 1)]).circle(1.6).extrude(0.6)
    cable = cq.Workplane("YZ").workplane(offset=-45.2 / 2 - 4).center(0, 8).rect(9, 4).extrude(4)
    return case.union(boss).union(spline).union(screws).union(cable)


def pliers():
    """Slip-joint pliers lying flat, a stand-in hand tool for the tool-dock demo: tapered jaws,
    a round pivot, two handles splaying from it, 165 mm long and 11 mm thick."""
    from shapely.geometry import Polygon, Point
    from shapely.ops import unary_union
    jaws = Polygon([(0, -3), (0, 3), (46, 8.5), (46, -8.5)])
    pivot = Point(52, 0).buffer(11.5, 32)
    handle = lambda s: Polygon([(56, s * 1.0), (58, s * 11.0), (165, s * 27.0), (165, s * 15.0)])
    outline = unary_union([jaws, pivot, handle(1), handle(-1)]).buffer(1.2).buffer(-1.2).simplify(0.05)
    return cq.Workplane("XY").polyline(list(outline.exterior.coords)[:-1]).close().extrude(11)


def scissors():
    """Paper scissors lying flat, closed, a stand-in for the tool-fingers demo: blades tapering
    to a point, a pivot, and two finger loops of different sizes; 160 mm long, 7 mm thick."""
    from shapely.geometry import Polygon, Point
    from shapely.affinity import scale as sscale
    from shapely.ops import unary_union
    blades = Polygon([(0, -1.0), (0, 1.0), (88, 8.0), (88, -8.0)])
    pivot = Point(88, 0).buffer(8, 32)
    ring = lambda cx, cy, ax, ay, ix, iy: sscale(Point(cx, cy).buffer(1, 64), ax, ay).difference(sscale(Point(cx, cy).buffer(1, 64), ix, iy))
    loops = [ring(140, 15, 20, 13, 14, 8), ring(136, -16, 17, 12, 11.5, 7.5)]
    shanks = [Polygon([(90, 3), (92, 9), (123, 15), (122, 6)]), Polygon([(90, -3), (92, -9), (121, -16), (121, -6)])]
    shape = unary_union([blades, pivot, *loops, *shanks]).buffer(0.8).buffer(-0.8)
    wp = cq.Workplane("XY").polyline(list(shape.exterior.coords)[:-1]).close()
    for hole in shape.interiors:
        wp = wp.polyline(list(hole.coords)[:-1]).close()
    return wp.extrude(7)


PARTS = {"bracket": (bracket, "0.80,0.25,0.15"), "l_bracket": (l_bracket, "0.15,0.35,0.75"),
         "gear": (gear, "0.85,0.55,0.10"), "wedge_stand": (wedge_stand, "0.20,0.55,0.30"),
         "servo": (servo, "0.07,0.07,0.08"), "sts3215": (sts3215, "0.03,0.03,0.035"),
         "pliers": (pliers, "0.78,0.12,0.10"), "scissors": (scissors, "0.10,0.30,0.80")}


def main(names=None):
    for name, (make, colour) in PARTS.items():
        if names and name not in names:
            continue
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
    import sys
    main(sys.argv[1:])
