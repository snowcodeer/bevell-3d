"""Visual hull from calibrated photos and object masks, at true scale on the sheet."""
import numpy as np, trimesh
from skimage import measure
from .project import project

# The white area inside the markers, in world mm, and how tall an object may be. Above the
# object, points out of most photos' frames are carved by none, so only what rests on the sheet
# is kept (on_sheet): with a 160 mm ceiling the 162 mm clock lost its top, and raising it alone
# grew a floating tower up to the ceiling over Mario and the clock.
AREA_LO = np.array([31.0, 31.0, 0.0])
AREA_HI = np.array([266.0, 179.0, 250.0])


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


def on_sheet(occ, reach=3):
    """The occupied cells connected to the bottom layer: the object, not what floats above it.
    Connection is judged on the cells grown by `reach`, so a thin neck still joins (the clock's
    stem and loop handle came apart at 2 mm cells and were dropped)."""
    from scipy import ndimage
    grown = ndimage.binary_dilation(occ, iterations=reach)
    lab, n = ndimage.label(grown)
    base = set(np.unique(lab[:, :, :reach + 2])) - {0}
    return occ & np.isin(lab, list(base)) if base else np.zeros_like(occ)


def visual_hull(views, masks, step=0.75, coarse=2.0, smooth=True):
    """Coarse carve over the whole white area to find the object, then a fine one round it."""
    pts, cshape = grid(AREA_LO, AREA_HI, coarse)
    sel = pts[on_sheet(carve(pts, views, masks).reshape(cshape)).ravel()]
    if len(sel) == 0:
        raise ValueError("Nothing is left standing on the sheet once every photo has its say: check the photos "
                         "show the object, in the middle of the sheet.")
    lo = sel.min(0) - 2 * coarse; hi = sel.max(0) + 2 * coarse; lo[2] = 0.0
    fine, shape = grid(lo, hi, step)
    occ = on_sheet(carve(fine, views, masks).reshape(shape))
    occ[:, :, 0] = occ[:, :, 1]          # it rests on the paper
    vol = np.pad(occ.astype(np.float32), 1)
    verts, faces, _, _ = measure.marching_cubes(vol, 0.5)
    mesh = trimesh.Trimesh((verts - 1) * step + lo, faces)
    if mesh.volume < 0:
        mesh.invert()
    if smooth:
        trimesh.smoothing.filter_taubin(mesh, lamb=0.5, nu=-0.53, iterations=25)
    return mesh
