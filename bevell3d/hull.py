"""Visual hull from calibrated photos and object masks, at true scale on the sheet."""
import numpy as np, trimesh
from skimage import measure
from .project import project

# The white area inside the markers, in world mm, and how tall an object may be.
AREA_LO = np.array([31.0, 31.0, 0.0])
AREA_HI = np.array([266.0, 179.0, 160.0])


def grid(lo, hi, step):
    xs, ys, zs = [np.arange(lo[i], hi[i] + step / 2, step) for i in range(3)]
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    return np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1), (len(xs), len(ys), len(zs))


def carve(pts, views, masks):
    """Keep points every photo sees inside the object (outside a photo's frame says nothing)."""
    keep = np.ones(len(pts), bool)
    for v, m in zip(views, masks):
        uv = np.round(project(pts, v)).astype(int)
        h, w = m.shape
        inb = (uv[:, 0] >= 0) & (uv[:, 0] < w) & (uv[:, 1] >= 0) & (uv[:, 1] < h)
        hit = np.zeros(len(pts), bool)
        hit[inb] = m[uv[inb, 1], uv[inb, 0]]
        keep &= hit | ~inb
    return keep


def visual_hull(views, masks, step=0.75, coarse=2.0, smooth=True):
    """Coarse carve over the whole white area to find the object, then a fine one round it."""
    pts, _ = grid(AREA_LO, AREA_HI, coarse)
    sel = pts[carve(pts, views, masks)]
    if len(sel) == 0:
        raise ValueError("nothing survives every photo: check the masks and poses")
    lo = sel.min(0) - 2 * coarse; hi = sel.max(0) + 2 * coarse; lo[2] = 0.0
    fine, shape = grid(lo, hi, step)
    occ = carve(fine, views, masks).reshape(shape)
    occ[:, :, 0] = occ[:, :, 1]          # it rests on the paper
    vol = np.pad(occ.astype(np.float32), 1)
    verts, faces, _, _ = measure.marching_cubes(vol, 0.5)
    mesh = trimesh.Trimesh((verts - 1) * step + lo, faces)
    if mesh.volume < 0:
        mesh.invert()
    if smooth:
        trimesh.smoothing.filter_taubin(mesh, lamb=0.5, nu=-0.53, iterations=25)
    return mesh
