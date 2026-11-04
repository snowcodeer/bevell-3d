"""blend_join: a smooth fillet where an arm meets a body, and nothing else changed."""
import time
import numpy as np
import trimesh
from bevell3d.blend import blend_join


def _parts():
    body = trimesh.creation.box(bounds=[[-20, -20, -6], [20, 20, 0]])          # a plate
    arm = trimesh.creation.box(bounds=[[-4, -4, -1], [4, 4, 25]])              # a post sunk 1 mm into it
    return body, arm


def test_fillet_added_only_at_the_joint():
    body, arm = _parts()
    plain = trimesh.boolean.union([body, arm], engine="manifold")
    t = time.time()
    out = blend_join(body, arm, radius=3.0, pitch=0.25)
    assert time.time() - t < 30
    assert out.is_watertight
    # A 3 mm concave fillet round a 32 mm perimeter: (1 - pi/4) r^2 per mm, about 62 mm3.
    added = out.volume - plain.volume
    assert 25 < added < 140, added
    pts, _ = trimesh.sample.sample_surface_even(out, 20000, seed=0)
    moved = trimesh.proximity.closest_point(plain, pts)[1]
    far = trimesh.proximity.closest_point(arm, pts)[1] > 4.0
    assert moved[far].max() < 1e-3                                             # the rest is the exact mesh
    assert moved[~far].max() > 0.5                                             # the corner did fill


def test_no_contact_returns_plain_union():
    body, _ = _parts()
    away = trimesh.creation.box(bounds=[[50, 50, 50], [55, 55, 60]])
    out = blend_join(body, away)
    assert abs(out.volume - (body.volume + away.volume)) < 1e-3
