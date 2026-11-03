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
    box = trimesh.creation.box((50.1, 46.2, 21.2))
    box.apply_translation((150, 100, 10.6))
    h, info, pocket, outer = holder_cad(box, HolderParams())
    assert info["valid"]
    assert np.allclose(info["pocket_outline_mm"], (50.1 + 0.8, 46.2 + 0.8), atol=0.25), info
    hm = to_mesh(h)
    inter = trimesh.boolean.intersection([hm, seated(box)], engine="manifold")
    assert len(inter.faces) == 0 or inter.volume < 0.5
