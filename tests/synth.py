"""Synthetic photos of the capture sheet from known cameras, for tests."""
import numpy as np, cv2
from bevell3d.sheet import raster, load_layout

PPM = 8.0


def look_at(centre, target=(148.5, 105.0, 0.0)):
    """World-to-camera rotation and translation (OpenCV: x right, y down, z forward)."""
    c = np.asarray(centre, float); f = np.asarray(target, float) - c; f /= np.linalg.norm(f)
    right = np.cross(f, [0, 0, 1.0]); right /= np.linalg.norm(right)
    down = np.cross(f, right)
    R = np.stack([right, down, f])
    return R, -R @ c


def camera_at(elev_deg, azim_deg, dist, target=(148.5, 105.0, 0.0)):
    e, a = np.radians(elev_deg), np.radians(azim_deg)
    t = np.asarray(target, float)
    return t + dist * np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])


def photo(K, R, t, size=(1536, 1152), seed=0):
    L = load_layout()
    sheet = raster(PPM, L)
    A = np.array([[1 / PPM, 0, 0], [0, -1 / PPM, L["page_mm"][1]], [0, 0, 1]])
    H = K @ np.c_[R[:, 0], R[:, 1], t] @ A
    img = cv2.warpPerspective(sheet, H, size, flags=cv2.INTER_AREA, borderValue=110)
    rng = np.random.default_rng(seed)
    img = cv2.GaussianBlur(img, (0, 0), 0.7).astype(np.float32) + rng.normal(0, 3, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)
