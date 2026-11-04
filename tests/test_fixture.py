import json, numpy as np, trimesh
from bevell3d.fixture import fixture_cad, write_fixture


def test_a_fixture_has_reliefs_on_the_squeeze_axis_and_the_pick_in_the_tag_frame(tmp_path):
    can = trimesh.creation.cylinder(radius=30, height=100, sections=96)
    can.apply_translation((150, 105, 50))
    solid, rep = fixture_cad(can)
    assert solid.isValid() and rep["fixture"]["valid"]
    assert rep["fixture"]["relief_mm"] >= 26                          # an SO-101 jaw with pads, and room
    g = rep["grasp"]
    # The part is on the far side of the tag along x, half its height above the floor.
    assert g["centre_mm"][0] > 30 and abs(g["centre_mm"][1]) < 0.5 and 40 < g["centre_mm"][2] < 60, g
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
