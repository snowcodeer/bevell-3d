import json, numpy as np, trimesh
from bevell3d.fixture import fixture_cad, write_fixture


def test_a_fixture_has_reliefs_on_the_squeeze_axis_and_the_pick_in_the_tag_frame(tmp_path):
    can = trimesh.creation.cylinder(radius=30, height=100, sections=96)
    can.apply_translation((150, 105, 50))
    solid, rep = fixture_cad(can)
    assert solid.isValid() and rep["fixture"]["valid"]
    assert rep["fixture"]["relief_mm"] >= 26                          # an SO-101 jaw with pads, and room
    g = rep["grasp"]
    # The part is beyond the tag's top edge (y), on its centre line, half its height up.
    assert g["centre_mm"][1] > 30 and abs(g["centre_mm"][0]) < 0.5 and 40 < g["centre_mm"][2] < 60, g
    assert abs(abs(g["squeeze_axis"][1]) - 1) < 1e-3 or abs(abs(g["squeeze_axis"][0]) - 1) < 1e-3
    assert g["pregrasp_mm"][2] > g["centre_mm"][2] + 100
    rep = write_fixture(str(tmp_path), can)
    for f in ("fixture.step", "fixture.stl", "fixture.3mf", "fixture.json", "tag.pdf"):
        assert (tmp_path / f).exists(), f
    assert trimesh.load(tmp_path / "fixture.stl").is_watertight
    assert open(tmp_path / "tag.pdf", "rb").read(4) == b"%PDF"


def test_the_printed_tag_is_found_by_a_camera_with_its_id_and_size():
    import cv2
    from bevell3d.fixture import tag_page, TAG_ID, TAG_DICT, TAG_MM
    page = np.asarray(tag_page(dpi=300))
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, TAG_DICT)))
    corners, ids, _ = det.detectMarkers(page)
    assert ids is not None and ids.ravel().tolist() == [TAG_ID]
    side = np.linalg.norm(corners[0][0][0] - corners[0][0][1])
    assert abs(side / (TAG_MM / 25.4 * 300) - 1) < 0.015, side          # corners sit a hair outside the edge


def test_the_pick_preview_finds_the_tag_where_the_camera_sees_it():
    import cv2
    from bevell3d.fixture import TAG_ID, TAG_DICT, TAG_MM
    from tools.pick_preview import preview
    W, H, f = 1920, 1440, 1600.0
    K = np.array([[f, 0, W / 2], [0, f, H / 2], [0, 0, 1.0]])
    marker = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, TAG_DICT)), TAG_ID, 400)
    marker = cv2.copyMakeBorder(marker, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    h = TAG_MM / 2
    # The marker faces the camera (its z towards it), tilted 35 degrees and turned 10.
    Rx = cv2.Rodrigues(np.array([np.radians(180 - 35), 0.0, 0.0]))[0]; Rz = cv2.Rodrigues(np.array([0.0, 0.0, np.radians(10)]))[0]
    rvec = cv2.Rodrigues(Rz @ Rx)[0].ravel(); tvec = np.array([20.0, -10.0, 300.0])
    corners3d = np.array([[-h, h, 0], [h, h, 0], [h, -h, 0], [-h, -h, 0]])
    uv, _ = cv2.projectPoints(corners3d, rvec, tvec, K, None)
    src = np.float32([[40, 40], [440, 40], [440, 440], [40, 440]])
    img = cv2.warpPerspective(marker, cv2.getPerspectiveTransform(src, uv.reshape(-1, 2).astype(np.float32)), (W, H), borderValue=255)
    rep = {"tag": {"dictionary": TAG_DICT, "id": TAG_ID, "size_mm": TAG_MM},
           "grasp": {"centre_mm": [0, 52, 55], "squeeze_axis": [1, 0, 0], "approach": [0, 0, -1], "jaw_closed_on_part_mm": 68, "pregrasp_mm": [0, 52, 200]}}
    out, info = preview(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), rep, focal_px=f)
    assert abs(info["tag_distance_mm"] - np.linalg.norm(tvec)) < 3, info
    assert out.shape == (H, W, 3)
