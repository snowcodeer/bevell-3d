"""A mesh handed over in a generator's frame (Y up, unit size, turned) comes back at true size."""
import numpy as np, trimesh, cv2
from scipy.spatial.transform import Rotation
from bevell3d.fit import fit
from bevell3d.hull import visual_hull
from bevell3d.project import silhouette
from tests.synth import look_at, camera_at
from tests.test_markers import K_TRUE, SIZE

CAMS = [camera_at(45, a, 380) for a in range(0, 360, 60)] + \
       [camera_at(10, a, 370) for a in range(0, 360, 45)] + [camera_at(85, 90, 330)]


def l_bracket():
    """Asymmetric, so the turn about the vertical is identifiable: 60 x 40 x 12 plus a 15 x 40 x 30 upright."""
    a = trimesh.creation.box((60, 40, 12)); a.apply_translation((30, 20, 6))
    b = trimesh.creation.box((15, 40, 30)); b.apply_translation((7.5, 20, 15))
    m = trimesh.boolean.union([a, b], engine="manifold")
    m.apply_translation((120, 85, 0))
    return m


def test_generated_frame_is_recovered():
    truth = l_bracket()
    views = []
    for c in CAMS:
        R, t = look_at(c)
        views.append({"rv": cv2.Rodrigues(R)[0], "tv": t.reshape(3, 1), "K": K_TRUE})
    masks = [silhouette(truth, v, SIZE) for v in views]
    guide = visual_hull(views, masks, step=1.0)
    # What a generator hands over: Y up, about unit size, turned 37 degrees, off-centre.
    gen = truth.copy()
    gen.apply_translation(-gen.bounding_box.centroid)
    gen.apply_transform(trimesh.transformations.rotation_matrix(np.radians(37), [0, 0, 1]))
    gen.apply_transform(trimesh.transformations.rotation_matrix(np.radians(-90), [1, 0, 0]))   # Z up -> Y up
    gen.apply_scale(1 / 70.0); gen.apply_translation((0.2, -0.1, 0.05))
    world, rep = fit(gen, views, masks, SIZE, guide, log=lambda *_: None)
    ext = world.bounds[1] - world.bounds[0]
    assert np.allclose(ext, truth.bounds[1] - truth.bounds[0], atol=1.0), (ext, rep)
    assert np.allclose(world.bounds, truth.bounds, atol=1.5), (world.bounds, truth.bounds)
    assert rep["mean_iou_quarter_res"] > 0.93, rep
