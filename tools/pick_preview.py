"""Where the robot will pick: find the fixture's tag in a camera image and draw the planned grasp.

    .venv/bin/python -m tools.pick_preview photo.jpg fixture.json [--focal-px 1500] [--out pick.jpg]

Prints the grasp in the camera's frame (mm). A robot controller composes that with its own
camera-to-base calibration; this tool needs only the camera's focal length (estimated from the
image width if not given, which is enough for a preview, not for a pick).
"""
import argparse, json
import numpy as np, cv2


def find_tag(img, rep, K):
    """(rvec, tvec) of the fixture's tag, in mm, or None."""
    tag = rep["tag"]
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX      # depth hangs on the corners
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, tag["dictionary"])), params)
    corners, ids, _ = det.detectMarkers(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img)
    if ids is None or tag["id"] not in ids.ravel():
        return None
    c = corners[list(ids.ravel()).index(tag["id"])][0]
    h = tag["size_mm"] / 2
    obj = np.array([[-h, h, 0], [h, h, 0], [h, -h, 0], [-h, -h, 0]], np.float64)   # OpenCV's corner order
    ok, rvec, tvec = cv2.solvePnP(obj, c.astype(np.float64), K, None, flags=cv2.SOLVEPNP_IPPE_SQUARE)
    return (rvec, tvec) if ok else None


def preview(img, rep, focal_px=None):
    h, w = img.shape[:2]
    f = focal_px or 1.1 * w
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])
    pose = find_tag(img, rep, K)
    if pose is None:
        raise ValueError(f"tag {rep['tag']['id']} is not in the image")
    rvec, tvec = pose
    g = rep["grasp"]
    c = np.array(g["centre_mm"]); s = np.array(g["squeeze_axis"]); half = g["jaw_closed_on_part_mm"] / 2
    pts = np.array([c, c - s * half, c + s * half, np.array(g["pregrasp_mm"])], np.float64)
    uv, _ = cv2.projectPoints(pts, rvec, tvec, K, None)
    uv = uv.reshape(-1, 2).astype(int)
    out = img.copy()
    cv2.drawFrameAxes(out, K, None, rvec, tvec, rep["tag"]["size_mm"] * 0.8, 3)
    cv2.line(out, tuple(uv[1]), tuple(uv[2]), (255, 160, 40), 4)                  # where the jaws close
    for p in uv[1:3]:
        cv2.circle(out, tuple(p), 9, (255, 160, 40), -1)
    cv2.arrowedLine(out, tuple(uv[3]), tuple(uv[0]), (40, 220, 120), 3, tipLength=0.08)   # approach from above
    cv2.circle(out, tuple(uv[0]), 7, (40, 220, 120), -1)
    R, _ = cv2.Rodrigues(rvec)
    cam = (R @ c + tvec.ravel()).round(1).tolist()
    cv2.putText(out, f"grasp at {cam} mm from the camera", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)
    return out, {"grasp_camera_mm": cam, "squeeze_axis_camera": (R @ s).round(4).tolist(),
                 "approach_camera": (R @ np.array(g["approach"])).round(4).tolist(), "tag_distance_mm": round(float(np.linalg.norm(tvec)), 1)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image"); ap.add_argument("fixture"); ap.add_argument("--focal-px", type=float); ap.add_argument("--out", default="pick.jpg")
    a = ap.parse_args()
    out, info = preview(cv2.imread(a.image), json.load(open(a.fixture)), a.focal_px)
    cv2.imwrite(a.out, out)
    print(json.dumps(info, indent=1))
