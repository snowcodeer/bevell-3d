"""A vase (radius changing with height) comes back with its profile, from synthetic photos."""
import numpy as np, trimesh, cv2
from bevell3d.revolve import revolved
from bevell3d.project import silhouette
from tests.synth import look_at, camera_at
from tests.test_markers import K_TRUE, SIZE

CAMS = [camera_at(45, a, 400) for a in range(0, 360, 45)] + \
       [camera_at(10, a, 400) for a in range(0, 360, 30)] + [camera_at(85, 90, 360)]


def true_radius(z):
    return 30 - 12 * np.sin(np.pi * z / 110) ** 2 + (z > 95) * -8      # waisted body and a neck


def test_vase_profile_and_axis():
    zs = np.linspace(0, 110, 111)
    vase = trimesh.creation.revolve(np.c_[[0, *true_radius(zs), 0], [0, *zs, 110]], sections=128)
    vase.apply_translation((145, 108, 0))
    views = []
    for c in CAMS:
        R, t = look_at(c)
        views.append({"rv": cv2.Rodrigues(R)[0], "tv": t.reshape(3, 1), "K": K_TRUE})
    masks = [silhouette(vase, v, SIZE) for v in views]
    mesh, rep = revolved(views, masks, step=0.5)
    assert np.allclose(rep["axis_mm"], (145, 108), atol=0.6), rep["axis_mm"]
    assert abs(rep["height_mm"] - 110) < 3.5, rep["height_mm"]
    for z, d in rep["profile_mm"]:
        if 5 < z < 90:                                   # away from the ends, where carving is loosest
            assert abs(d - 2 * true_radius(z)) < 1.6, (z, d, 2 * true_radius(z))
    assert mesh.is_watertight
