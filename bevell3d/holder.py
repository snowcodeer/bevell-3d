"""A printable holder that the scanned object drops into and lifts straight out of.

The object lifts out vertically, so the space it needs is everything above its underside
inside its footprint: pocket(x, y, z) holds when (x, y) is in the footprint and z is above
the underside at (x, y). That is grown by a print clearance, cut from a nest that follows
the footprint at a set wall thickness, and two finger notches are cut across the narrow
side so the object can be gripped. Built on a voxel grid and meshed by marching cubes.
"""
import numpy as np, trimesh, cv2
from scipy import ndimage
from skimage import measure


def underside(mesh, pitch):
    """Per column of a top-down grid: the object's lowest z (inf outside its footprint)."""
    pts = mesh.sample(max(20000, int(mesh.area / (pitch * pitch) * 2)))
    pts = np.vstack([pts, mesh.vertices])
    lo = mesh.bounds[0][:2] - 1.0
    ij = np.floor((pts[:, :2] - lo) / pitch).astype(int)
    shape = tuple(ij.max(0) + 2)
    z = np.full(shape, np.inf)
    np.minimum.at(z, (ij[:, 0], ij[:, 1]), pts[:, 2])
    foot = np.isfinite(z)
    filled = ndimage.binary_fill_holes(ndimage.binary_closing(foot, iterations=2))
    # Columns sampling missed inside the footprint take the lowest neighbour's depth.
    if (filled & ~foot).any():
        zf = np.where(foot, z, np.inf)
        for _ in range(6):
            zf = np.where(filled & ~np.isfinite(zf), ndimage.minimum_filter(zf, size=3), zf)
        z = np.where(filled, zf, np.inf)
    return z, lo


def make_holder(obj, clearance=0.4, wall=3.0, floor=2.0, depth_fraction=0.5, max_depth=30.0,
                notch_radius=9.0, pitch=None, smooth=True, max_faces=200000):
    """obj: true-size mesh resting on z = 0. Returns (holder mesh, report).

    The grid is 0.2 mm for small parts and coarsens with size, to 0.4 mm at most: a 166 mm
    mug at 0.2 mm is 100 million cells and several GB, which ran a 16 GB laptop out of memory
    with five scans at once (3 Nov 2026). The gap stays between clearance and clearance + pitch."""
    if pitch is None:
        pitch = float(np.clip(max(obj.extents[:2]) / 400.0, 0.2, 0.4))
    height = float(obj.bounds[1][2] - obj.bounds[0][2])
    depth = min(depth_fraction * height, max_depth)
    z_under, lo = underside(obj, pitch)
    foot = np.isfinite(z_under)
    # Grow the footprint by the clearance; under the grown edge the pocket floor is the
    # lowest underside nearby, so the object never lands on a lip.
    # The object's edge lies within half a column of its last column's centre, and the
    # meshed pocket wall half a column beyond the pocket's last centre, so growing by
    # ceil(clearance / pitch) whole columns leaves a gap of clearance to clearance + pitch.
    r_clear = np.ceil(clearance / pitch - 1e-9) + 0.01
    disk = lambda r: (lambda k: (k[0] ** 2 + k[1] ** 2) <= r * r)(np.mgrid[-int(r) - 1:int(r) + 2, -int(r) - 1:int(r) + 2])
    pad = int((clearance + wall + notch_radius) / pitch) + 4
    z_under = np.pad(np.where(foot, z_under, 1e9), pad, constant_values=1e9)
    foot = np.pad(foot, pad)
    lo = lo - pad * pitch
    pocket_foot = ndimage.binary_dilation(foot, disk(r_clear))
    z_floor = ndimage.minimum_filter(z_under, footprint=disk(r_clear))
    z_floor = np.where(pocket_foot, np.minimum(z_floor, 1e9), 1e9) - clearance
    # The nest: footprint grown by clearance and wall, smoothed round.
    outer = ndimage.binary_dilation(pocket_foot, disk(wall / pitch))
    outer = cv2.GaussianBlur(outer.astype(np.float32), (0, 0), 1.5 / pitch) > 0.5
    # Finger notches across the narrow side, through the wall down to 60% of the depth.
    ii, jj = np.nonzero(foot)
    c = np.array([ii.mean(), jj.mean()]); cov = np.cov(np.c_[ii, jj].T)
    w, V = np.linalg.eigh(cov); minor = V[:, 0]
    proj = (np.c_[ii, jj] - c) @ minor
    notch_centres = [c + minor * proj.min(), c + minor * proj.max()]
    I, J = np.mgrid[0:foot.shape[0], 0:foot.shape[1]]
    notch = np.zeros_like(foot)
    for nc in notch_centres:
        notch |= (I - nc[0]) ** 2 + (J - nc[1]) ** 2 <= (notch_radius / pitch) ** 2
    total = floor + depth
    zs = np.arange(0, total + pitch / 2, pitch)
    solid = np.zeros(foot.shape + (len(zs),), bool)
    for k, z in enumerate(zs):
        cut = pocket_foot & (z >= floor + z_floor)
        if z >= floor + 0.4 * depth:
            cut |= notch & outer
        solid[:, :, k] = outer & ~cut
    vol = np.pad(solid.astype(np.float32), 1)
    if smooth:
        vol = ndimage.gaussian_filter(vol, 0.6)
    verts, faces, _, _ = measure.marching_cubes(vol, 0.5, spacing=(pitch, pitch, pitch))
    # Column i covers [lo + i*pitch, lo + (i+1)*pitch), so its sample sits at the middle.
    verts = verts - pitch + np.array([lo[0] + pitch / 2, lo[1] + pitch / 2, 0.0])
    holder = trimesh.Trimesh(verts, faces)
    if holder.volume < 0:
        holder.invert()
    if smooth:                                       # take the grid's steps off the walls
        trimesh.smoothing.filter_taubin(holder, lamb=0.5, nu=-0.53, iterations=10)
    if len(holder.faces) > max_faces:                # a 0.2 mm grid makes a million faces
        small = holder.simplify_quadric_decimation(face_count=max_faces)
        if small.is_watertight:
            holder = small
    pocket_ext = (np.ptp(np.nonzero(pocket_foot)[0]) + 1) * pitch, (np.ptp(np.nonzero(pocket_foot)[1]) + 1) * pitch
    report = {"object_mm": [round(float(e), 1) for e in obj.bounds[1] - obj.bounds[0]],
              "holder_mm": [round(float(e), 1) for e in holder.bounds[1] - holder.bounds[0]],
              "pocket_depth_mm": round(depth, 1), "clearance_mm": clearance, "grid_mm": round(pitch, 2), "wall_mm": wall, "floor_mm": floor,
              "pocket_footprint_mm": [round(float(e), 1) for e in pocket_ext],
              "watertight": bool(holder.is_watertight), "volume_cm3": round(float(holder.volume) / 1000, 1)}
    return holder, report


def seated(obj, floor=2.0):
    """The object where it sits in the holder (for previews)."""
    m = obj.copy(); m.apply_translation((0, 0, floor - m.bounds[0][2]))
    return m
