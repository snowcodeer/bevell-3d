"""A smooth fillet where an arm meets a body, for printed parts.

`blend_join(body, arm)` returns `body ∪ arm` with material added in the concave corner where the
two meet, so the arm grows out of the body instead of standing on it. Only that corner changes:
the fillet is the morphological closing of the union with a ball of `radius`, kept to cells
within `radius` of both the arm and the body, meshed with marching cubes and unioned onto the
exact meshes. Everything else (the SO-101's screw holes, the servo horn's pocket, the arm's
own faces) keeps its original triangles.

Work is local: a voxel box round the joint (where the arm sinks into the body), padded by
radius + 4 mm, so a 3 mm fillet on an SO-101 jaw takes a second or two. Any failure returns the
plain union and logs why; it never raises.
"""
import logging
import numpy as np
import trimesh
from matplotlib.path import Path
from scipy import ndimage

log = logging.getLogger(__name__)


def _manifold(m):
    from manifold3d import Manifold, Mesh
    return Manifold(Mesh(vert_properties=np.asarray(m.vertices, np.float32), tri_verts=np.asarray(m.faces, np.uint32)))


def _occupancy(mesh, origin, shape, pitch):
    """Voxel centres inside `mesh`, layer by layer: each z layer is the mesh's cross-section
    (manifold3d's slice, holes included) filled by even-odd point tests."""
    man = _manifold(mesh)
    nx, ny, nz = shape
    xs = origin[0] + (np.arange(nx) + 0.5) * pitch
    ys = origin[1] + (np.arange(ny) + 0.5) * pitch
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    pts = np.c_[X.ravel(), Y.ravel()]
    occ = np.zeros(shape, bool)
    zlo, zhi = mesh.bounds[0][2], mesh.bounds[1][2]
    for k in range(nz):
        z = origin[2] + (k + 0.5) * pitch
        if z < zlo or z > zhi:
            continue
        polys = man.slice(z).to_polygons()
        if not polys:
            continue
        inside = np.zeros(len(pts), bool)
        for poly in polys:
            if len(poly) >= 3:
                inside ^= Path(np.asarray(poly)).contains_points(pts)
        occ[:, :, k] = inside.reshape(nx, ny)
    return occ


def _box(lo, hi):
    return trimesh.creation.box(bounds=[lo, hi])


def blend_join(body, arm, radius=3.0, pitch=0.25, margin=None):
    """`body ∪ arm` with a smooth concave fillet of about `radius` mm where they meet. Both are
    watertight meshes in mm that overlap at the joint."""
    try:
        plain = trimesh.boolean.union([body, arm], engine="manifold")
    except Exception as e:                                 # nothing else can work either
        log.warning("blend_join: plain union failed: %s", e)
        return trimesh.util.concatenate([body, arm])
    try:
        return _blend(body, arm, plain, radius, pitch, margin)
    except Exception as e:
        log.warning("blend_join: fillet skipped (%s: %s), plain union returned", type(e).__name__, e)
        return plain


def _blend(body, arm, plain, radius, pitch, margin):
    margin = radius + 4.0 if margin is None else margin
    # The joint: where the arm sinks into the body (padded by a little, for an arm that only touches).
    joint = trimesh.boolean.intersection([arm, body], engine="manifold")
    if joint is None or len(joint.faces) == 0:
        near = trimesh.boolean.intersection([arm, _box(body.bounds[0] - 1.0, body.bounds[1] + 1.0)], engine="manifold")
        if near is None or len(near.faces) == 0:
            raise ValueError("arm does not meet the body")
        joint = near
    lo = joint.bounds[0] - margin
    hi = joint.bounds[1] + margin
    shape = tuple(int(v) for v in np.ceil((hi - lo) / pitch))
    if np.prod(shape) > 12_000_000:
        raise ValueError(f"joint box too large ({shape})")
    # Each mesh cut to the box first: slicing a small piece is quicker than the whole jaw.
    cut = _box(lo - pitch, hi + pitch)
    b = trimesh.boolean.intersection([body, cut], engine="manifold")
    a = trimesh.boolean.intersection([arm, cut], engine="manifold")
    ob = _occupancy(b, lo, shape, pitch)
    oa = _occupancy(a, lo, shape, pitch)
    occ = ob | oa
    # Closing with a ball of `radius`: dilate by distance outside, erode by distance inside.
    r = radius / pitch
    dil = ndimage.distance_transform_edt(~occ) <= r
    closed = ndimage.distance_transform_edt(dil) > r
    # Only the corner between the two: cells within `radius` of both, so a screw hole or a notch
    # of the body itself is never filled.
    d_arm = ndimage.distance_transform_edt(~oa)
    d_body = ndimage.distance_transform_edt(~ob)
    added = closed & ~occ & (d_arm <= r + 0.5) & (d_body <= r + 0.5)
    if added.sum() < 8:
        return plain
    keep = occ | added
    # A smooth surface: the signed distance of the filled shape, lightly blurred, positive outside.
    sd = ndimage.distance_transform_edt(~keep) - ndimage.distance_transform_edt(keep)
    sd = ndimage.gaussian_filter(sd.astype(np.float32), 1.0)
    # The fillet piece: the smooth surface, limited to a band round the added cells that reaches
    # into the solid, so it overlaps the exact meshes and adds nothing anywhere else.
    band = ndimage.distance_transform_edt(~added) - 2.5
    f = np.maximum(sd, band).astype(np.float32)
    f = np.pad(f, 1, constant_values=float(f.max()) + 1.0)
    from skimage.measure import marching_cubes
    verts, faces, _, _ = marching_cubes(f, level=0.0, gradient_direction="ascent")
    verts = lo + (verts - 1 + 0.5) * pitch
    piece = trimesh.Trimesh(verts, faces, process=True)
    piece.fix_normals()
    if piece.volume < 0:
        piece.invert()
    out = trimesh.boolean.union([plain, piece], engine="manifold")
    if out is None or not out.is_watertight or out.volume < plain.volume - 1e-3:
        raise ValueError("blended mesh not watertight")
    return out
