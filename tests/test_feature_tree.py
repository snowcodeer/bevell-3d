import py_compile, tempfile, os, math
import pytest
from bevell3d.feature_tree import ev, validate, to_cadquery, write_fusion_script

BOTTLE = {
    "parameters": [
        {"name": "body_d", "value": 60, "min": 40, "max": 80, "what": "body diameter"},
        {"name": "body_h", "value": 90, "min": 60, "max": 120, "what": "body height"},
        {"name": "cap_d", "value": 44, "min": 30, "max": 60, "what": "cap diameter"},
        {"name": "cap_h", "value": 20, "min": 10, "max": 30, "what": "cap height"},
        {"name": "cap_r", "value": 1.5, "min": 0.2, "max": 4, "what": "cap edge round"},
    ],
    "steps": [
        {"id": "body", "op": "revolve", "profile": [[0, 0], ["body_d/2", 0], ["body_d/2", "body_h - 12"], ["cap_d/2", "body_h"], [0, "body_h"]]},
        {"id": "cap", "op": "extrude", "shape": {"circle": {"d": "cap_d"}}, "from_z": "body_h", "height": "cap_h"},
        {"id": "cap_round", "op": "fillet", "edges": "top", "radius": "cap_r"},
    ],
}

MUG = {
    "parameters": [
        {"name": "d", "value": 82, "min": 60, "max": 100, "what": "outer diameter"},
        {"name": "h", "value": 95, "min": 70, "max": 120, "what": "height"},
        {"name": "wall", "value": 4, "min": 2, "max": 8, "what": "wall"},
        {"name": "reach", "value": 28, "min": 15, "max": 45, "what": "handle reach"},
        {"name": "grip", "value": 11, "min": 6, "max": 16, "what": "handle thickness"},
    ],
    "steps": [
        {"id": "body", "op": "revolve", "profile": [[0, 0], ["d/2", 0], ["d/2", "h"], [0, "h"]]},
        {"id": "hollow", "op": "shell", "thickness": "wall", "open": "top"},
        {"id": "handle", "op": "sweep", "section": {"circle": {"d": "grip"}},
         "path": {"plane": "XZ", "points": [["d/2 - wall", "h*0.78"], ["d/2 + reach", "h*0.55"], ["d/2 - wall", "h*0.25"]]}},
    ],
}


def test_expressions_are_arithmetic_only():
    assert ev("body_d/2 + sqrt(16) - min(3, 4)", {"body_d": 60}) == 31
    for bad in ("__import__('os')", "body_d.real", "open('x')", "[1][0]"):
        with pytest.raises(ValueError):
            ev(bad, {"body_d": 60})


@pytest.mark.parametrize("tree", [BOTTLE, MUG], ids=["bottle", "mug"])
def test_trees_build_in_cadquery_and_write_a_fusion_script(tree):
    validate(tree)
    p = {q["name"]: q["value"] for q in tree["parameters"]}
    shape, warns = to_cadquery(tree, p)
    assert shape.isValid() and shape.Volume() > 0, warns
    bb = shape.BoundingBox()
    if tree is BOTTLE:
        assert abs(bb.xlen - 60) < 0.1 and abs(bb.zlen - 110) < 0.1
        # body cylinder + taper + cap, a little under the bare cylinders for the rounds
        v = math.pi * 30 ** 2 * 78 + math.pi * 12 / 3 * (30 ** 2 + 30 * 22 + 22 ** 2) + math.pi * 22 ** 2 * 20
        assert abs(shape.Volume() / v - 1) < 0.03
    else:
        assert bb.xlen > 82 + 20, "the handle reaches out past the body"
        assert shape.Volume() < math.pi * 41 ** 2 * 95 * 0.5, "the mug is hollow"
    with tempfile.TemporaryDirectory() as d:
        path = write_fusion_script(os.path.join(d, "BevellModel"), tree, p, "test")
        py_compile.compile(path, doraise=True)
        assert os.path.exists(os.path.join(d, "BevellModel", "BevellModel.manifest"))


def test_a_lofts_corner_edges_are_vertical_and_a_chamfer_is_capped_to_the_round_it_follows():
    """The servo's tree: a box lofted through three rectangles, its vertical edges rounded at
    0.7 mm, then a 1.3 mm chamfer round the bottom. OpenCascade makes the loft's corner edges
    B-splines, which CadQuery's |Z selector skipped while Fusion rounded them; and a chamfer
    wider than the corner rounds it runs along fails in Fusion. Both kernels now pick edges by
    where they lie and cap the chamfer the same way."""
    import cadquery as cq
    from bevell3d.feature_tree import to_cadquery, select_edges, edge_radius, validate
    rect = {"rect": {"w": "w", "l": "d"}}
    tree = {"parameters": [{"name": n, "value": v, "min": v / 2, "max": v * 2} for n, v in
                           (("w", 40), ("d", 20), ("h", 30), ("r", 0.7), ("c", 1.3))],
            "steps": [{"id": "body", "op": "loft", "sections": [{"shape": rect, "z": 0}, {"shape": rect, "z": "h / 2"}, {"shape": rect, "z": "h"}]},
                      {"id": "soft", "op": "fillet", "edges": "vertical", "radius": "r"},
                      {"id": "trim", "op": "chamfer", "edges": "bottom", "radius": "c"}]}
    validate(tree)
    P = {q["name"]: q["value"] for q in tree["parameters"]}
    loft, _ = to_cadquery(dict(tree, steps=tree["steps"][:1]), P)
    assert len(select_edges(loft, "vertical")) == 4                        # the four corners, B-splines or not
    rounded, _ = to_cadquery(dict(tree, steps=tree["steps"][:2]), P)
    radii = sorted(edge_radius(e) for e in select_edges(rounded, "bottom"))
    assert abs(radii[0] - 0.7) < 0.01 and radii[-1] == float("inf"), radii  # four corner rounds, four straight sides
    shape, warns = to_cadquery(tree, P)
    assert any("trim: chamfer capped from 1.30 to 0.63 mm" in w for w in warns), warns
    assert shape.isValid() and len(shape.Solids()) == 1
