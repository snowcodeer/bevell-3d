import numpy as np, trimesh
from bevell3d.gripper import make_pads, PadParams


def test_pads_hold_a_cylinder_without_cutting_into_it():
    can = trimesh.creation.cylinder(radius=25, height=80, sections=96)
    can.apply_translation((150, 105, 40))
    p = PadParams()
    pads, grasp = make_pads(can, p)
    for name, pr in pads.items():
        assert pr["print"].is_watertight, name
        inter = trimesh.boolean.intersection([pr["world"], can], engine="manifold")
        assert len(inter.faces) == 0 or inter.volume < 1.0, (name, inter.volume)
        # flat back on the bed, pad no bigger than the jaw
        assert pr["print"].bounds[0][2] == 0
        assert pr["print"].extents[0] <= p.width + 1 and pr["print"].extents[1] <= p.height + 1
    # Closed on the can, the pads' backs sit one diameter plus clearance and thickness apart each side.
    assert abs(grasp["closed_on_object_mm"] - (50 + 2 * (p.clearance + p.thickness))) < 1.0, grasp
    assert np.allclose(grasp["centre_mm"][:2], (150, 105), atol=0.5)
