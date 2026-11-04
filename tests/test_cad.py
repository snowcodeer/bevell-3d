import numpy as np, trimesh
from bevell3d.cad import to_cad, holder_cad, to_mesh, HolderParams
from bevell3d.holder import seated


def test_a_round_object_becomes_a_revolve_and_keeps_its_hole():
    zs = np.linspace(0, 50, 51)
    ring = trimesh.creation.annulus(r_min=38, r_max=58.5, height=50, sections=128)
    ring.apply_translation((150, 105, 25))
    solid, kind, info, _ = to_cad(ring, "revolved")
    assert kind == "revolved" and info["ring"], (kind, info)
    assert abs(info["max_diameter_mm"] - 117) < 1.0 and abs(info["hole_diameter_mm"] - 76) < 1.0, info
    assert abs(solid.Volume() / ring.volume - 1) < 0.02


def test_holder_cad_takes_the_object_with_its_clearance():
    from shapely.geometry import LineString, Point
    box = trimesh.creation.box((50.1, 46.2, 21.2))
    box.apply_translation((150, 100, 10.6))
    # The notch fillet crashes OpenCascade on a box; holder_cad_safe drops it in production.
    h, info, pocket, outer = holder_cad(box, HolderParams(), skip=("notch",))
    assert info["valid"] and info["dfm"]["pocket_clear_of_footprint"], info
    # Even clearance on the flat sides, not the worst corner's. A smooth curve bulges a little
    # beside a perfectly sharp corner, which a scan never has; the corners stay under 1.2 mm.
    x0, x1, y0, y1 = 124.95, 175.05, 76.9, 123.1
    sides = [LineString([(x0, y0), (x1, y0)]), LineString([(x1, y0), (x1, y1)]), LineString([(x1, y1), (x0, y1)]), LineString([(x0, y1), (x0, y0)])]
    gap = np.array([min(sd.distance(Point(q)) for sd in sides) for q in np.asarray(pocket.exterior.coords)])
    assert gap.min() > 0.3 and np.median(gap) < 0.6 and gap.max() < 1.2, (gap.min(), np.median(gap), gap.max())
    for k in ("lead_in_chamfer_mm", "top_fillet_mm", "foot_chamfer_mm"):
        assert info["dfm"][k] == {"lead_in_chamfer_mm": 0.8, "top_fillet_mm": 1.36, "foot_chamfer_mm": 0.4}[k], info["dfm"]
    hm = to_mesh(h)
    assert hm.is_watertight
    inter = trimesh.boolean.intersection([hm, seated(box)], engine="manifold")
    assert len(inter.faces) == 0 or inter.volume < 0.5


def test_a_round_footprint_gets_a_true_circle_and_every_edge_treatment():
    can = trimesh.creation.cylinder(radius=30, height=40, sections=96)
    can.apply_translation((150, 105, 20))
    h, info, pocket, outer = holder_cad(can)
    assert info["valid"] and info["dfm"]["outline"] == "circle", info
    assert all(isinstance(info["dfm"][k], float) for k in ("lead_in_chamfer_mm", "top_fillet_mm", "foot_chamfer_mm", "notch_fillet_mm")), info["dfm"]
    assert abs(info["pocket_outline_mm"][0] - 60.8) < 0.5, info   # 0.2 mm raster


def test_a_shell_open_underneath_is_filled_and_an_open_top_mug_is_not():
    from bevell3d.cad import solidify
    outer = trimesh.creation.box((80, 50, 30)); outer.apply_translation((150, 105, 15))
    inner = trimesh.creation.box((72, 42, 28)); inner.apply_translation((150, 105, 13))   # open at the bottom
    shell = trimesh.boolean.difference([outer, inner], engine="manifold")
    filled, rep = solidify(shell)
    assert rep["filled"] and abs(filled.volume / outer.volume - 1) < 0.06, (rep, filled.volume / outer.volume)
    mug_out = trimesh.creation.cylinder(radius=40, height=90, sections=64); mug_out.apply_translation((150, 105, 45))
    mug_in = trimesh.creation.cylinder(radius=35, height=90, sections=64); mug_in.apply_translation((150, 105, 50))  # open at the top
    mug = trimesh.boolean.difference([mug_out, mug_in], engine="manifold")
    same, rep = solidify(mug)
    assert not rep["filled"] and same is mug, rep


def test_a_stepped_bracket_becomes_stacked_extrusions_and_a_sloped_stand_does_not():
    import numpy as np
    from bevell3d.cad import prismatic_cad
    from bevell3d.feature_tree import to_cadquery, validate
    from tools.make_parts import bracket, wedge_stand

    def mesh_of(make):
        s = make().val(); vs, fs = s.tessellate(0.02, 0.1)
        m = trimesh.Trimesh(np.array([v.toTuple() for v in vs]), np.array(fs)); m.apply_translation(-m.bounds[0]); return m

    m = mesh_of(bracket)
    solid, info, tree = prismatic_cad(m)
    assert info["levels"] == 2 and info["holes"] == 3 and info["level_heights_mm"] == [8.0, 22.0], info
    assert abs(solid.Volume() / m.volume - 1) < 0.01
    validate(tree)
    rebuilt, _ = to_cadquery(tree, {q["name"]: q["value"] for q in tree["parameters"]})
    assert abs(rebuilt.Volume() / m.volume - 1) < 0.01
    assert {q["name"] for q in tree["parameters"]} == {"level1_h", "level2_h", "hole1_d", "hole2_d", "hole3_d"}
    solid, why, tree = prismatic_cad(mesh_of(wedge_stand))
    assert solid is None and "levels" in why, why


def test_a_servo_keeps_its_ear_height_between_slices():
    """The ears start at 26.5 mm, half way between two 1 mm slices: the boundary is found by
    halving the gap, not put at the slices' midpoint (which gave 26.0)."""
    import numpy as np
    from bevell3d.cad import prismatic_cad
    from bevell3d.feature_tree import to_cadquery, validate
    from tools.make_parts import servo

    s = servo().val(); vs, fs = s.tessellate(0.02, 0.1)
    m = trimesh.Trimesh(np.array([v.toTuple() for v in vs]), np.array(fs)); m.apply_translation(-m.bounds[0])
    solid, info, tree = prismatic_cad(m)
    assert info["levels"] == 4 and info["holes"] == 4, info
    assert np.allclose(info["level_heights_mm"], [26.5, 2.5, 8.0, 5.0], atol=0.06), info
    validate(tree)
    rebuilt, _ = to_cadquery(tree, {q["name"]: q["value"] for q in tree["parameters"]})
    assert abs(rebuilt.Volume() / m.volume - 1) < 0.005
    holes = [q["value"] for q in tree["parameters"] if q["name"].startswith("hole")]
    assert len(holes) == 4 and all(abs(d - 4.4) < 0.1 for d in holes), holes
