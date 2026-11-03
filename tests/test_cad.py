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
