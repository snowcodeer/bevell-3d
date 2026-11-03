import numpy as np
from bevell3d import markers
from bevell3d.sheet import load_layout, raster
from tests.synth import camera_at, look_at, photo

SIZE = (1536, 1152)
F_TRUE = 1266.0
K_TRUE = np.array([[F_TRUE, 0, SIZE[0] / 2], [0, F_TRUE, SIZE[1] / 2], [0, 0, 1]])
# A ring at 45 degrees, a ring at 20 degrees and one from above, as the capture guide asks.
CAMERAS = [camera_at(45, a, 380) for a in range(0, 360, 60)] + \
          [camera_at(20, a, 420) for a in range(30, 360, 60)] + [camera_at(85, 90, 330)]


def test_raster_puts_every_marker_where_the_layout_says():
    L = load_layout()
    img = raster(10.0, L)
    det = markers.detector(L)
    corners, ids, _ = det.detectMarkers(img)
    assert sorted(ids.ravel().tolist()) == sorted(L["world"])
    for c, i in zip(corners, ids.ravel()):
        page = np.array(L["page_corners"][str(int(i))]) * 10.0
        assert np.abs(c.reshape(4, 2) - page).max() < 1.5


def test_lens_and_every_camera_are_recovered():
    images = []
    for k, c in enumerate(CAMERAS):
        R, t = look_at(c)
        images.append((str(k), photo(K_TRUE, R, t, SIZE, seed=k)))
    views, K, rms = markers.solve(images)
    assert len(views) == len(CAMERAS), [v["name"] for v in views]
    assert abs(K[0, 0] - F_TRUE) / F_TRUE < 0.01, K[0, 0]
    assert rms < 1.0
    for v in views:
        true = CAMERAS[int(v["name"])]
        assert np.linalg.norm(v["camera_mm"] - true) < 3.0, (v["name"], v["camera_mm"], true)
