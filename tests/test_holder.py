import numpy as np, trimesh
from bevell3d.holder import make_holder, seated


def _gap(holder, obj, depth):
    s = seated(obj)
    pts = s.sample(8000)
    pts = pts[(pts[:, 2] > 2.5) & (pts[:, 2] < 2 + depth - 0.5)]
    gap = -trimesh.proximity.ProximityQuery(holder).signed_distance(pts)
    return gap[gap < 2]                         # points facing a wall, not a finger notch


def test_box_drops_in_with_the_clearance_all_round():
    box = trimesh.creation.box((50.1, 46.2, 21.2))
    box.apply_translation((150, 100, 10.6))
    h, rep = make_holder(box)
    assert rep["watertight"]
    inter = trimesh.boolean.intersection([h, seated(box)], engine="manifold")
    assert len(inter.faces) == 0 or inter.volume < 0.5
    gap = _gap(h, box, rep["pocket_depth_mm"])
    assert 0.3 <= np.median(gap) <= 0.6, np.median(gap)
    assert np.percentile(gap, 95) < 0.7
    assert np.allclose(rep["holder_mm"][:2], (50.1 + 2 * 3.4, 46.2 + 2 * 3.4), atol=0.6), rep
