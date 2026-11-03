"""Camera poses and the lens from the capture sheet's markers.

Every marker corner found in a photo is a known point on the paper, so each photo gives
a pose by PnP and all photos together fix the focal length. Creases, a sheet that runs off
the frame and low side shots all still work, because any few markers are enough.
"""
import numpy as np, cv2
from .sheet import load_layout

F35_IPHONE_MAIN = 26.0   # mm, 35 mm equivalent; a starting guess only


def detector(layout):
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(layout["dictionary"]), params)


def detect(gray, layout, det=None):
    """Image and world points for every known marker corner in a greyscale photo."""
    corners, ids, _ = (det or detector(layout)).detectMarkers(gray)
    img, world, found = [], [], []
    if ids is None:
        return np.zeros((0, 2)), np.zeros((0, 3)), found
    for c, i in zip(corners, ids.ravel()):
        if int(i) in layout["world"]:
            img.append(c.reshape(4, 2)); world.append(layout["world"][int(i)]); found.append(int(i))
    return np.concatenate(img).astype(np.float64), np.concatenate(world), found


def guess_K(w, h, f35=F35_IPHONE_MAIN):
    f = f35 * np.hypot(w, h) / 43.27
    return np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])


def calibrate(obs, size, min_markers=4):
    """One shared focal length (square pixels, centred principal point, no distortion) from
    every photo with enough markers. Returns K and the RMS reprojection error in px."""
    use = [o for o in obs if len(o["found"]) >= min_markers]
    if len(use) < 3:
        return guess_K(*size), None
    flags = (cv2.CALIB_USE_INTRINSIC_GUESS | cv2.CALIB_FIX_PRINCIPAL_POINT | cv2.CALIB_FIX_ASPECT_RATIO
             | cv2.CALIB_ZERO_TANGENT_DIST | cv2.CALIB_FIX_K1 | cv2.CALIB_FIX_K2 | cv2.CALIB_FIX_K3)
    rms, K, _, _, _ = cv2.calibrateCamera([o["world"].astype(np.float32) for o in use],
                                          [o["img"].astype(np.float32) for o in use],
                                          size, guess_K(*size), np.zeros(5), flags=flags)
    return K, rms


def pose(o, K):
    """PnP for one photo: IPPE (exact for a plane) then Levenberg-Marquardt on all corners."""
    ok, rv, tv = cv2.solvePnP(o["world"], o["img"], K, None, flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        return None
    rv, tv = cv2.solvePnPRefineLM(o["world"], o["img"], K, None, rv, tv)
    proj, _ = cv2.projectPoints(o["world"], rv, tv, K, None)
    err = np.linalg.norm(proj.reshape(-1, 2) - o["img"], axis=1)
    R, _ = cv2.Rodrigues(rv)
    centre = (-R.T @ tv).ravel()
    return {"rv": rv, "tv": tv, "K": K, "err_px": float(np.median(err)), "camera_mm": centre}


def solve(images, layout=None, min_markers=4):
    """images: list of (name, BGR or grey array), all the same size. Returns one view dict per
    photo that has a pose (name, rv, tv, K, err_px, camera_mm, markers), the K and its RMS."""
    L = layout or load_layout()
    det = detector(L)
    obs = []
    for item in images:
        # (name, image) is used as is. (name, full_res_image, working_size) finds the markers
        # at full resolution and reports them in the working copy's pixels.
        name, im = item[0], item[1]
        gray = im if im.ndim == 2 else cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        img, world, found = detect(gray, L, det)
        size = gray.shape[::-1]
        if len(item) > 2:
            size = tuple(item[2])
            img = img * np.array([size[0] / gray.shape[1], size[1] / gray.shape[0]])
        obs.append({"name": name, "img": img, "world": world, "found": found, "size": size})
    size = obs[0]["size"]
    K, rms = calibrate(obs, size, min_markers)
    views = []
    for o in obs:
        if len(o["found"]) < min_markers:
            continue
        p = pose(o, K)
        if p is None or p["camera_mm"][2] <= 0:      # the camera must be above the paper
            continue
        p.update(name=o["name"], markers=len(o["found"]))
        views.append(p)
    return views, K, rms
