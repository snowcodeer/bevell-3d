"""Revolved route: a bottle, cup or knob standing upright, rebuilt from its radius profile.

Every horizontal slice of the visual hull is a polygon drawn round the true circle (each
photo's outline adds two tangent lines), so the circle that fits inside the slice is the
true one. The largest inscribed circle of each slice gives the radius at that height, and
the median of their centres the vertical axis. The profile is then revolved.
"""
import numpy as np, trimesh
from scipy import ndimage
from .hull import AREA_LO, AREA_HI, grid, carve, on_sheet


def profile(views, masks, step=0.5, coarse=2.0):
    # Only what rests on the sheet, as in the hull: since the carve reaches 250 mm, a floating
    # tower above the object stretched this fine grid to the ceiling and a scan took over 25
    # minutes here (4 Nov).
    pts, cshape = grid(AREA_LO, AREA_HI, coarse)
    sel = pts[on_sheet(carve(pts, views, masks).reshape(cshape)).ravel()]
    lo = sel.min(0) - 2 * coarse; hi = sel.max(0) + 2 * coarse; lo[2] = 0.0
    fine, shape = grid(lo, hi, step)
    occ = on_sheet(carve(fine, views, masks).reshape(shape))
    # A ring (a roll of tape) has a hole the top photos carve out; its slices are annuli, whose
    # inscribed circle sits in the wall. Filling them gives the outer profile, which is what a
    # holder needs (found on the benchmark's tape roll, 3 Nov 2026).
    occ = np.stack([ndimage.binary_fill_holes(occ[:, :, k]) for k in range(shape[2])], axis=2)
    zs = lo[2] + np.arange(shape[2]) * step
    centres, radii = [], []
    for k in range(shape[2]):
        sl = occ[:, :, k]
        if sl.sum() < 4:
            centres.append(None); radii.append(0.0); continue
        d = ndimage.distance_transform_edt(np.pad(sl, 1))[1:-1, 1:-1]
        # The centre of area: the inscribed circle's centre wandered 3 mm on a bottle whose
        # slices are near-regular polygons, where the distance peak is flat.
        ci, cj = ndimage.center_of_mass(sl)
        centres.append((lo[0] + ci * step, lo[1] + cj * step)); radii.append(d.max() * step)
    # Each slice's own largest inscribed circle gives its radius. Measuring every slice about one
    # common axis instead turned a 3 mm error in that axis into a bottle 6 mm too narrow
    # (benchmark, 3 Nov 2026).
    axis = np.median(np.array([c for c in centres if c is not None]), axis=0)
    r = np.array(radii)
    r = ndimage.median_filter(r, size=5)
    top = int(np.max(np.nonzero(r > step)[0])) if (r > step).any() else 0
    return axis, zs[:top + 1], r[:top + 1]


def revolve(axis, zs, r, sections=96):
    """A closed, watertight solid of revolution about a vertical axis."""
    rings = [(z, max(rr, 0.0)) for z, rr in zip(zs, r)]
    pts2 = [(0.0, rings[0][0])] + [(rr, z) for z, rr in rings] + [(0.0, rings[-1][0])]
    lin = np.array(pts2)
    mesh = trimesh.creation.revolve(lin, sections=sections)       # about +Z, profile in (r, z)
    mesh.apply_translation((axis[0], axis[1], 0.0))
    mesh.merge_vertices(); mesh.fix_normals()
    return mesh


def revolved(views, masks, step=0.5):
    axis, zs, r = profile(views, masks, step)
    mesh = revolve(axis, zs, r)
    rep = {"axis_mm": [round(float(a), 1) for a in axis], "height_mm": round(float(zs[-1]), 1),
           "max_diameter_mm": round(float(2 * r.max()), 1),
           "profile_mm": [[round(float(z), 1), round(float(2 * rr), 1)] for z, rr in zip(zs[::max(1, len(zs) // 12)], r[::max(1, len(zs) // 12)])]}
    return mesh, rep
