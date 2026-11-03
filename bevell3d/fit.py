"""Put any mesh at true size on the sheet by matching its outline in every calibrated photo.

A generated mesh (SAM 3D Objects) comes in its own frame and at an arbitrary scale. The
photos know the real size: we search the mesh's up axis and its turn about the vertical,
then refine scale, turn, tilt and position with Nelder-Mead on the mean silhouette IoU,
keeping the mesh resting on the paper. An optional second stage lets each of the mesh's
own axes stretch by up to 15%, for a generator that got the proportions slightly wrong.
"""
import numpy as np, trimesh
from scipy.optimize import minimize
from scipy.spatial.transform import Rotation
from .project import silhouette, iou

UP_AXES = {"+x": [1, 0, 0], "-x": [-1, 0, 0], "+y": [0, 1, 0], "-y": [0, -1, 0], "+z": [0, 0, 1], "-z": [0, 0, -1]}


def _up_to_z(up):
    """Rotation taking the mesh's `up` direction to world +Z."""
    up = np.asarray(up, float)
    if np.allclose(up, [0, 0, 1]):
        return np.eye(3)
    if np.allclose(up, [0, 0, -1]):
        return Rotation.from_euler("x", 180, degrees=True).as_matrix()
    axis = np.cross(up, [0, 0, 1.0]); axis /= np.linalg.norm(axis)
    return Rotation.from_rotvec(axis * np.arccos(np.clip(up[2], -1, 1))).as_matrix()


class Fitter:
    def __init__(self, mesh, views, masks, size, scale=0.25, faces=1500):
        m = mesh.copy()
        if len(m.faces) > faces:
            m = m.simplify_quadric_decimation(face_count=faces)
        self.centre = m.bounding_box.centroid
        self.verts = m.vertices - self.centre            # the mesh about its own middle
        self.faces = m.faces
        self.views, self.size, self.scale = views, size, scale
        self.masks = [silhouette_mask_small(mk, scale) for mk in masks]

    def place(self, p, stretch=(1, 1, 1)):
        """p = (up-rotation matrix index into self.ups, yaw, tilt_x, tilt_y, log_scale, x, y)."""
        R0, yaw, tx, ty, ls, x, y = p
        R = Rotation.from_euler("zxy", [yaw, tx, ty]).as_matrix() @ R0
        v = (self.verts * np.asarray(stretch)) @ R.T * np.exp(ls)
        v[:, 2] -= v[:, 2].min()                          # resting on the paper
        v[:, 0] += x - (v[:, 0].max() + v[:, 0].min()) / 2
        v[:, 1] += y - (v[:, 1].max() + v[:, 1].min()) / 2
        return v

    def score(self, verts):
        m = trimesh.Trimesh(verts, self.faces, process=False)
        return float(np.mean([iou(silhouette(m, v, self.size, self.scale), mk) for v, mk in zip(self.views, self.masks)]))


def silhouette_mask_small(mask, scale):
    import cv2
    h, w = mask.shape
    return cv2.resize(mask.astype(np.uint8), (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) > 0


def fit(mesh, views, masks, size, guide, yaw_step=15, stretch=True, log=print):
    """guide: a rough true-scale mesh in world (the visual hull) for the start position and size.
    Returns the fitted world mesh and a report."""
    F = Fitter(mesh, views, masks, size)
    gx, gy = (guide.bounds[0][:2] + guide.bounds[1][:2]) / 2
    g_ext = guide.bounds[1] - guide.bounds[0]
    cands = []
    for name, up in UP_AXES.items():
        R0 = _up_to_z(up)
        h = np.ptp((F.verts @ R0.T)[:, 2])
        ls = np.log(g_ext[2] * 0.95 / h)                 # start at the hull's height (it runs tall)
        for yaw in np.radians(np.arange(0, 360, yaw_step)):
            p = (R0, yaw, 0.0, 0.0, ls, gx, gy)
            cands.append((F.score(F.place(p)), name, p))
    cands.sort(key=lambda c: -c[0])
    log(f"search: best {cands[0][0]:.3f} with up {cands[0][1]}")
    best = None
    for s0, name, (R0, yaw, tx, ty, ls, x, y) in cands[:4]:
        f = lambda q: -F.score(F.place((R0, *q)))
        x0 = np.array([yaw, tx, ty, ls, x, y])
        simplex = np.array([x0] + [x0 + np.eye(6)[k] * d for k, d in enumerate([0.15, 0.08, 0.08, 0.06, 3.0, 3.0])])
        r = minimize(f, x0, method="Nelder-Mead", options={"initial_simplex": simplex, "maxfev": 400, "xatol": 1e-3, "fatol": 1e-4})
        if best is None or -r.fun > best[0]:
            best = (-r.fun, name, R0, r.x)
    score, name, R0, q = best
    log(f"refined: {score:.3f}")
    st = (1.0, 1.0, 1.0)
    if stretch:
        f = lambda s: -F.score(F.place((R0, *q), np.exp(np.clip(s, -0.14, 0.14))))
        r = minimize(f, np.zeros(3), method="Nelder-Mead",
                     options={"initial_simplex": np.array([[0, 0, 0], [0.05, 0, 0], [0, 0.05, 0], [0, 0, 0.05]]), "maxfev": 200})
        if -r.fun > score + 0.005:
            st, score = tuple(np.exp(np.clip(r.x, -0.14, 0.14))), -r.fun
            log(f"stretched {np.round(st, 3)}: {score:.3f}")
    # Apply the same transform to the full-resolution mesh.
    full = mesh.copy()
    Fh = Fitter.__new__(Fitter); Fh.verts = full.vertices - F.centre
    world = trimesh.Trimesh(Fitter.place(Fh, (R0, *q), st), full.faces, process=False)
    world.fix_normals()
    yaw, tx, ty, ls, x, y = q
    report = {"up_axis": name, "yaw_deg": round(float(np.degrees(yaw)) % 360, 1),
              "tilt_deg": [round(float(np.degrees(tx)), 1), round(float(np.degrees(ty)), 1)],
              "scale": float(np.exp(ls)), "stretch": [round(float(s), 3) for s in st],
              "mean_iou_quarter_res": round(score, 3),
              "extents_mm": [round(float(e), 1) for e in world.bounds[1] - world.bounds[0]]}
    return world, report
