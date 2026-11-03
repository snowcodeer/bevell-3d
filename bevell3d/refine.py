"""Refine every camera from the sheet's whole outline, with one shared focal length.

Each view's pose starts from the corner solution. The residual is the distance from
points on the sheet mask's boundary to the projected A4 rectangle; points on the
photo's border (the sheet runs off the frame) are dropped, and a robust loss keeps
hands and creases from pulling the fit.
"""
import numpy as np, cv2
from scipy.optimize import least_squares

A4 = (297.0, 210.0)
RECT = np.array([[0, 0, 0], [A4[0], 0, 0], [A4[0], A4[1], 0], [0, A4[1], 0]], np.float64)


def boundary_points(sheet, obj, n=500):
    m = (sheet | obj).astype(np.uint8)
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
    h, w = sheet.shape
    keep = (c[:, 0] > 3) & (c[:, 1] > 3) & (c[:, 0] < w - 4) & (c[:, 1] < h - 4)
    c = c[keep]
    if len(c) > n:
        c = c[np.linspace(0, len(c) - 1, n).astype(int)]
    return c


def seg_dist(p, a, b):
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(ab @ ab, 1e-9), 0, 1)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


def residuals(x, views, w, h, free_aspect=False):
    f = x[0]
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])
    rect = RECT.copy()
    if free_aspect:
        rect[2:, 1] = x[-1]
    out = []
    for i, v in enumerate(views):
        rv = x[1 + 6 * i:4 + 6 * i]; tv = x[4 + 6 * i:7 + 6 * i]
        q, _ = cv2.projectPoints(rect, rv, tv, K, None)
        q = q.reshape(4, 2)
        d = np.min([seg_dist(v["bpts"], q[k], q[(k + 1) % 4]) for k in range(4)], axis=0)
        out.append(d)
    return np.concatenate(out)


def refine(views, f0, size, free_aspect=False):
    w, h = size
    x0 = [f0]
    for v in views:
        rv, tv, _ = v["cands"][0]
        x0 += list(np.ravel(rv)) + list(np.ravel(tv))
    if free_aspect:
        x0 += [A4[1]]
    before = residuals(np.array(x0), views, w, h, free_aspect)
    sol = least_squares(residuals, np.array(x0), args=(views, w, h, free_aspect), loss="soft_l1", f_scale=3.0, max_nfev=600)
    after = residuals(sol.x, views, w, h, free_aspect)
    if free_aspect:
        print(f"fitted sheet: 297.0 x {sol.x[-1]:.1f} mm (A4 is 297 x 210, US Letter 279 x 216)")
    f = sol.x[0]
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])
    S = np.diag([-1.0, -1.0, 1.0]); d = np.array([[A4[0]], [A4[1]], [0.0]])
    for i, v in enumerate(views):
        rv = sol.x[1 + 6 * i:4 + 6 * i].reshape(3, 1); tv = sol.x[4 + 6 * i:7 + 6 * i].reshape(3, 1)
        R, _ = cv2.Rodrigues(rv)
        R2 = R @ S; t2 = tv - R2 @ d                     # the same sheet, labelled the other way round
        v["cands"] = [(rv, tv, 0.0), (cv2.Rodrigues(R2)[0], t2, 0.0)]
        v["K"] = K
    return f, float(np.median(before)), float(np.median(after))
