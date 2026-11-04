import json, os
import numpy as np, pytest, trimesh
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
    pdf = open(tmp_path / "tag.pdf", "rb").read()
    import re
    assert pdf[:4] == b"%PDF" and len(re.findall(rb"/Type\s*/Page(?![s\w])", pdf)) == 2      # pick tag, place tag
    assert rep["tag"]["id"] == 40 and rep["tag"]["place_id"] == 41


def test_the_printed_tags_are_found_by_a_camera_with_their_ids_and_size():
    import cv2
    from bevell3d.fixture import tag_page, TAG_ID, PLACE_TAG_ID, TAG_DICT, TAG_MM
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, TAG_DICT)))
    for tag_id in (TAG_ID, PLACE_TAG_ID):
        page = np.asarray(tag_page(tag_id, dpi=300, role="Place fixture"))
        corners, ids, _ = det.detectMarkers(page)
        assert ids is not None and ids.ravel().tolist() == [tag_id]
        side = np.linalg.norm(corners[0][0][0] - corners[0][0][1])
        assert abs(side / (TAG_MM / 25.4 * 300) - 1) < 0.015, side      # corners sit a hair outside the edge


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
    # The place fixture's tag is looked for only when asked, and found the same way.
    with pytest.raises(ValueError, match="tag 41"):
        preview(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), rep, focal_px=f, tag_id=41)
    place = cv2.copyMakeBorder(cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, TAG_DICT)), 41, 400),
                               40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    img41 = cv2.warpPerspective(place, cv2.getPerspectiveTransform(src, uv.reshape(-1, 2).astype(np.float32)), (W, H), borderValue=255)
    _, info41 = preview(cv2.cvtColor(img41, cv2.COLOR_GRAY2BGR), rep, focal_px=f, tag_id=41)
    assert abs(info41["tag_distance_mm"] - info["tag_distance_mm"]) < 0.5, info41


@pytest.mark.skipif(not os.path.exists("/Applications/Blender.app/Contents/MacOS/Blender"), reason="needs Blender")
def test_the_pick_found_in_a_rendered_scene_lands_on_the_true_grasp(tmp_path):
    """The whole chain: fixture, tag frame, sticker turn, detection, pose. Rendered from a known
    camera, the grasp read off the image must land where it really is."""
    import subprocess, cv2
    from bevell3d.fixture import write_fixture
    from tools.make_parts import bracket
    from tools.pick_preview import preview
    s = bracket().val(); vs, fs = s.tessellate(0.05, 0.2)
    part = trimesh.Trimesh(np.array([v.toTuple() for v in vs]), np.array(fs)); part.apply_translation((150 - part.centroid[0], 105 - part.centroid[1], -part.bounds[0][2]))
    part.export(tmp_path / "model.stl")
    rep = write_fixture(str(tmp_path), part)
    cv2.imwrite(str(tmp_path / "tag_texture.png"), cv2.aruco.generateImageMarker(
        cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, rep["tag"]["dictionary"])), rep["tag"]["id"], 600))
    subprocess.run(["/Applications/Blender.app/Contents/MacOS/Blender", "-b", "-P", "tools/render_fixture_scene.py", "--",
                    "--dir", str(tmp_path), "--out", str(tmp_path / "scene.png")], check=True, capture_output=True, timeout=600)
    cam = json.load(open(tmp_path / "camera.json"))
    _, info = preview(cv2.imread(str(tmp_path / "scene.png")), rep, focal_px=cam["K"][0][0])
    t = rep["tag_in_holder"]; R = np.array([t["x_axis"], t["y_axis"], t["z_axis"]]).T
    w2c = np.array(cam["world_to_camera_m"])
    truth = (w2c[:3, :3] @ ((np.array(t["origin_mm"]) + R @ np.array(rep["grasp"]["centre_mm"])) / 1000) + w2c[:3, 3]) * 1000
    err = np.array(info["grasp_camera_mm"]) - truth
    assert np.linalg.norm(err[:2]) < 2 and np.linalg.norm(err) < 6, (err, truth)
