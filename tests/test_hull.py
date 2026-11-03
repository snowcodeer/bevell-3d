"""The visual hull is an outer bound: never smaller than the object, and only a little larger.

Measured on these synthetic sets: a box comes back about 1.5 mm wider on each side (in
perspective, a point just off a face projects inside the face's outline from most cameras)
and, without photos from near the table, far too tall. A ring of photos at about 10 degrees
above the table brings the height to within 3 mm, which is why the capture guide asks for one.
"""
import numpy as np, trimesh, cv2
from bevell3d import markers
from bevell3d.hull import visual_hull
from bevell3d.project import silhouette
from tests.synth import look_at, photo, camera_at
from tests.test_markers import K_TRUE, SIZE

CAMS = [camera_at(45, a, 380) for a in range(0, 360, 60)] + \
       [camera_at(10, a, 370) for a in range(0, 360, 30)] + [camera_at(85, 90, 330)]


def views_and_masks(obj):
    """Cameras recovered from synthetic sheet photos; masks drawn with the true cameras."""
    images, truth = [], {}
    for k, c in enumerate(CAMS):
        R, t = look_at(c)
        images.append((str(k), photo(K_TRUE, R, t, SIZE, seed=k)))
        truth[str(k)] = {"rv": cv2.Rodrigues(R)[0], "tv": t.reshape(3, 1), "K": K_TRUE}
    views, _, _ = markers.solve(images)
    assert len(views) == len(CAMS)
    return views, [silhouette(obj, truth[v["name"]], SIZE) for v in views]


def check(mesh, true, over=3.5):
    ext = mesh.bounds[1] - mesh.bounds[0]
    assert np.all(ext > np.asarray(true) - 0.75), ext
    assert np.all(ext < np.asarray(true) + over), ext


def test_box_comes_back_close_to_its_size():
    box = trimesh.creation.box((50.1, 46.2, 21.2))
    box.apply_translation((150, 100, 10.6))
    check(visual_hull(*views_and_masks(box), step=0.75), (50.1, 46.2, 21.2))


def test_bottle_height_and_diameter():
    bottle = trimesh.creation.cylinder(radius=33.0, height=90.0, sections=96)
    bottle.apply_translation((140, 110, 45))
    check(visual_hull(*views_and_masks(bottle), step=1.0), (66, 66, 90))
