"""Nudge each camera so the shape carved by the OTHER views lines up with this view's
SAM outline (silhouette consistency). Leave-one-out keeps a view from agreeing with itself."""
import numpy as np, cv2
from scipy.optimize import minimize

DS = 4  # work on masks at 1/4 size


def _small(mask):
    h, w = mask.shape
    return cv2.resize(mask.astype(np.uint8), (w // DS, h // DS), interpolation=cv2.INTER_AREA) > 0


def _proj(pts, rv, tv, K):
    p, _ = cv2.projectPoints(pts, rv, tv, K, None)
    return p.reshape(-1, 2) / DS


def _carve(pts, views, skip):
    keep = np.ones(len(pts), bool)
    for j, v in enumerate(views):
        if j == skip:
            continue
        uv = _proj(pts, v["rv"], v["tv"], v["K"])
        u = np.round(uv[:, 0]).astype(int); w_ = np.round(uv[:, 1]).astype(int)
        h, w = v["small"].shape
        inb = (u >= 0) & (u < w) & (w_ >= 0) & (w_ < h)
        hit = np.zeros(len(pts), bool); hit[inb] = v["small"][w_[inb], u[inb]]
        keep &= hit | ~inb
    return pts[keep]


def _iou(pts, v, rv, tv, radius):
    h, w = v["small"].shape
    img = np.zeros((h, w), np.uint8)
    uv = np.round(_proj(pts, rv, tv, v["K"])).astype(int)
    ok = (uv[:, 0] >= 0) & (uv[:, 0] < w) & (uv[:, 1] >= 0) & (uv[:, 1] < h)
    img[uv[ok, 1], uv[ok, 0]] = 1
    img = cv2.dilate(img, np.ones((radius, radius), np.uint8)) > 0
    a, b = img, v["small"]
    return (a & b).sum() / max(1, (a | b).sum())


def _edge_cost(v, rv, tv):
    """Robust mean distance (px) from the sheet's visible edge to the projected A4 rectangle."""
    from .refine import RECT, seg_dist
    q, _ = cv2.projectPoints(RECT, rv, tv, v["K"], None); q = q.reshape(4, 2)
    d = np.min([seg_dist(v["bpts"], q[k], q[(k + 1) % 4]) for k in range(4)], axis=0)
    return float(np.mean(2 * 3.0 * (np.sqrt(1 + (d / 3.0) ** 2) - 1)))   # soft L1, 3 px scale


def refine_silhouettes(views, lo, hi, step=1.5, rounds=3, edge_weight=0.03):
    xs, ys, zs = [np.arange(lo[i], hi[i] + step / 2, step) for i in range(3)]
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    pts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1)
    for v in views:
        v["small"] = _small(v["mask"])
    radius = 3
    history = []
    for r in range(rounds):
        scores = []
        for i, v in enumerate(views):
            others = _carve(pts, views, i)
            if len(others) == 0:
                scores.append(0.0); continue
            x0 = np.r_[np.ravel(v["rv"]), np.ravel(v["tv"])]
            f = lambda x: -_iou(others, v, x[:3].reshape(3, 1), x[3:].reshape(3, 1), radius) \
                + edge_weight * _edge_cost(v, x[:3].reshape(3, 1), x[3:].reshape(3, 1))
            simplex = np.array([x0] + [x0 + np.eye(6)[k] * (0.01 if k < 3 else 2.0) for k in range(6)])
            res = minimize(f, x0, method="Nelder-Mead", options={"initial_simplex": simplex, "maxfev": 250, "xatol": 1e-4, "fatol": 1e-4})
            if -res.fun > -f(x0):
                v["rv"], v["tv"] = res.x[:3].reshape(3, 1), res.x[3:].reshape(3, 1)
            scores.append((round(_iou(others, v, v["rv"], v["tv"], radius), 3), round(_edge_cost(v, v["rv"], v["tv"]), 1)))
        history.append(scores)
    return history
