"""Turn a true-size model into CAD (STEP), and cut a parametric holder for it.

Three ways in, tried in order of how editable the result is:

- revolved: a round object (bottle, tape roll) becomes a profile sketch revolved about its
  axis, holes included. The profile comes from each slice's area, which with sixteen photos
  is within a few tenths of a millimetre of the true circle.
- lofted: a smooth single-piece object (a mouse) becomes a loft through closed splines, one
  per horizontal slice, each resampled to the same number of points from the same bearing.
- mesh: anything else (a figure with separate limbs) is written as its triangles sewn into a
  closed STEP solid. It opens in any CAD package but is not a feature model.

Every candidate is checked against the mesh it came from (volume within 8%); one that is
not is dropped for the next way in.
"""
import os
from dataclasses import dataclass, asdict
import math
import numpy as np, trimesh, cv2
import cadquery as cq
from shapely.geometry import Polygon

SLICE_STEP = 1.0


def _slices(mesh, n=None, step=SLICE_STEP):
    lo, hi = mesh.bounds[0][2], mesh.bounds[1][2]
    zs = np.linspace(lo + 0.4, hi - 0.4, n) if n else np.arange(lo + 0.4, hi - 0.4, step)
    out = []
    for z in zs:
        sec = mesh.section(plane_origin=(0, 0, z), plane_normal=(0, 0, 1))
        if sec is None:
            out.append((z, [])); continue
        planar, T = sec.to_2D()
        polys = []
        for p in planar.polygons_full:
            q = trimesh.transform_points(np.c_[np.asarray(p.exterior.coords), np.zeros(len(p.exterior.coords))], T)[:, :2]
            holes = [trimesh.transform_points(np.c_[np.asarray(h.coords), np.zeros(len(h.coords))], T)[:, :2] for h in p.interiors]
            polys.append(Polygon(q, holes))
        polys.sort(key=lambda p: -p.area)
        out.append((z, polys))
    return out


def _check(solid, mesh, tol=0.08):
    try:
        v = solid.Volume()
    except Exception:
        return False, None
    ok = solid.isValid() and v > 0 and abs(v - mesh.volume) / mesh.volume < tol
    return ok, v


def _hugs(solid, mesh, frac=0.04, floor=2.0, samples=2000):
    """Whether a smooth fit stays on the scan. A loft through slices that change abruptly (a
    servo's ears) swung 30 mm outside the scan, in 60 pieces, with its volume 4% off and
    isValid() true, so neither check saw it. The fit's box must sit within `tol` of the
    scan's, and 95% of its surface within `tol` of the scan, `tol` being 4% of the scan's
    largest size or 2 mm, whichever is more."""
    tol = max(floor, frac * float(np.max(mesh.extents)))
    bb = solid.BoundingBox()
    lo, hi = mesh.bounds
    if (np.array([bb.xmin, bb.ymin, bb.zmin]) < lo - tol).any() or (np.array([bb.xmax, bb.ymax, bb.zmax]) > hi + tol).any():
        return False, f"reaches {tol:.1f} mm past the scan"
    vs, fs = solid.tessellate(0.2, 0.3)
    m = trimesh.Trimesh(np.array([v.toTuple() for v in vs]), np.array(fs), process=False)
    pts, _ = trimesh.sample.sample_surface(m, samples, seed=0)
    _, d, _ = trimesh.proximity.closest_point(mesh, pts)
    p95 = float(np.percentile(d, 95))
    return p95 < tol, f"95% of its surface within {p95:.1f} mm of the scan (limit {tol:.1f})"


# --- revolved -------------------------------------------------------------------------------

def revolved_cad(mesh, min_round=0.92):
    """A revolve, when every slice is one round loop (an optional round hole) about one axis."""
    sl = [(z, p) for z, p in _slices(mesh) if p]
    if len(sl) < 5 or any(len(p) > 1 and p[1].area > 0.02 * p[0].area for _, p in sl):
        return None, "slices are not single loops"
    cent = np.array([[p[0].centroid.x, p[0].centroid.y] for _, p in sl])
    axis = np.median(cent, axis=0)
    zs, ro, ri, rnd = [], [], [], []
    z0m, z1m = sl[0][0], sl[-1][0]
    for z, p in sl:
        outer = Polygon(p[0].exterior)
        r = np.sqrt(outer.area / np.pi)
        roundness = outer.area / (np.pi * max(np.linalg.norm(np.asarray(outer.exterior.coords) - axis, axis=1)) ** 2)
        if z0m + 0.1 * (z1m - z0m) < z < z1m - 0.1 * (z1m - z0m):    # the hull's ends are its least sure part
            rnd.append(roundness)
        hole = sum(Polygon(h).area for h in p[0].interiors)
        zs.append(z); ro.append(r); ri.append(np.sqrt(hole / np.pi) if hole > 0.01 * outer.area else 0.0)
    if np.median(rnd) < min_round or np.percentile(rnd, 10) < min_round - 0.05:
        return None, f"not round enough (median {np.median(rnd):.2f})"
    zs, ro, ri = np.array(zs), np.array(ro), np.array(ri)
    z0, z1 = mesh.bounds[0][2], mesh.bounds[1][2]
    ring = np.median(ri) > 1.0
    # Profile in the (r, z) half-plane, drawn on XZ and revolved about Z.
    side = [(float(r), float(z)) for r, z in zip(_smooth(ro), zs)][:: max(1, len(zs) // 40)]
    pts_out = [(side[0][0], z0)] + side + [(side[-1][0], z1)]
    if ring:
        # A straight bore at the median measured radius. Photos see down a hole only from
        # above, so the measured hole narrows towards its ends: the tape roll's 76 mm core
        # came out as a dish over a 35 mm hole. Tape cores, pipes and bearings are straight.
        rb = float(np.median(ri[ri > 0]))
        wp = cq.Workplane("XZ").moveTo(rb, z0).lineTo(*pts_out[0]).spline(pts_out[1:], includeCurrent=True) \
            .lineTo(rb, z1).close()
    else:
        wp = cq.Workplane("XZ").moveTo(0, z0).lineTo(*pts_out[0]).spline(pts_out[1:], includeCurrent=True).lineTo(0, z1).close()
    solid = wp.revolve(360, (0, 0, 0), (0, 1, 0)).translate((axis[0], axis[1], 0)).val()
    ok, v = _check(solid, mesh)
    info = {"axis_mm": [round(float(a), 2) for a in axis], "height_mm": round(float(z1 - z0), 1),
            "max_diameter_mm": round(float(2 * ro.max()), 1), "ring": bool(ring),
            "hole_diameter_mm": round(float(2 * np.median(ri)), 1) if ring else None,
            "profile_points": len(pts_out), "volume_ratio": round(v / mesh.volume, 3) if v else None}
    return (solid, info) if ok else (None, f"revolve failed the volume check: {info}")


def _smooth(v, k=5):
    v = np.asarray(v, float)
    if len(v) < k:
        return v
    pad = np.pad(v, k // 2, mode="edge")
    return np.convolve(pad, np.ones(k) / k, mode="valid")


# --- lofted ---------------------------------------------------------------------------------

def _resample(poly, n, centre):
    ring = np.asarray(poly.exterior.coords)[:-1]
    if Polygon(ring).exterior.is_ccw is False:
        ring = ring[::-1]
    seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(np.r_[ring, ring[:1]], axis=0), axis=1))]
    t = np.linspace(0, seg[-1], n, endpoint=False)
    pts = np.c_[np.interp(t, seg, np.r_[ring[:, 0], ring[0, 0]]), np.interp(t, seg, np.r_[ring[:, 1], ring[0, 1]])]
    # Start every section at the point due +X of the common centre, so the loft does not twist.
    ang = np.arctan2(pts[:, 1] - centre[1], pts[:, 0] - centre[0])
    return np.roll(pts, -int(np.argmin(np.abs(ang))), axis=0)


def _outline(polys):
    """A slice's outer outline: its loops merged and their holes filled. SAM 3D meshes carry
    loose inner surfaces, so one mouse slice came back as four overlapping loops."""
    from shapely.ops import unary_union
    u = unary_union([Polygon(p.exterior) for p in polys])
    parts = sorted(getattr(u, "geoms", [u]), key=lambda g: -g.area)
    return [Polygon(g.exterior) for g in parts]


def lofted_cad(mesh, sections=14, points=40):
    sl = [(z, _outline(p)) if p else (z, []) for z, p in _slices(mesh, n=sections)]
    if any(not p for _, p in sl):
        return None, "a slice is empty"
    if any(len(p) > 1 and p[1].area > 0.05 * p[0].area for _, p in sl):
        return None, "a slice has more than one piece (limbs, a handle)"
    centre = np.median([[p[0].centroid.x, p[0].centroid.y] for _, p in sl], axis=0)
    wires = []
    for z, p in sl:
        pts = _resample(p[0].simplify(0.15), points, centre)
        wires.append(cq.Wire.makePolygon([cq.Vector(x, y, z) for x, y in pts], close=True) if False else
                     cq.Wire.assembleEdges([cq.Edge.makeSpline([cq.Vector(x, y, z) for x, y in pts] + [cq.Vector(pts[0][0], pts[0][1], z)], periodic=False)]))
    try:
        solid = cq.Solid.makeLoft(wires, ruled=False)
    except Exception as e:
        return None, f"loft failed: {e}"
    # The loft's end caps sit 0.4 mm inside the mesh; extend nothing, report the ratio.
    ok, v = _check(solid, mesh, tol=0.10)
    info = {"sections": sections, "points_per_section": points, "volume_ratio": round(v / mesh.volume, 3) if v else None}
    if not ok:
        return None, f"loft failed the volume check: {info}"
    near, why = _hugs(solid, mesh)
    return (solid, {**info, "fit": why}) if near else (None, f"loft leaves the scan: {why}")


# --- mesh in STEP ---------------------------------------------------------------------------

def mesh_cad(mesh, faces=3000):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopoDS import TopoDS
    # Sewing is slow past a few thousand triangles (12,000 ran for a quarter of an hour), so
    # the mesh is remeshed closed first if decimating it alone will not keep it closed.
    src = mesh if mesh.is_watertight else clean_body(mesh)
    m = None
    for f in (faces, int(faces * 1.3), int(faces * 1.6)):   # decimation can open a closed mesh
        d = src.simplify_quadric_decimation(face_count=f) if len(src.faces) > f else src.copy()
        if d.is_watertight:
            m = d; break
    if m is None:                     # never sew the full mesh: 142,000 triangles took four minutes
        m = src.simplify_quadric_decimation(face_count=faces) if len(src.faces) > faces else src.copy()
    m.merge_vertices(); m.update_faces(m.nondegenerate_faces()); m.fix_normals()
    sew = BRepBuilderAPI_Sewing(1e-3)
    n = 0
    for f in m.faces:
        a, b, c = (cq.Vector(*m.vertices[i]) for i in f)
        try:
            sew.Add(cq.Face.makeFromWires(cq.Wire.makePolygon([a, b, c], close=True)).wrapped); n += 1
        except Exception:
            continue
    sew.Perform()
    shape = sew.SewedShape()
    if shape.ShapeType() == TopAbs_SHELL:
        solid = cq.Solid(ShapeFix_Solid().SolidFromShell(TopoDS.Shell_s(shape)))
        solid._source_mesh = m                       # to_mesh hands this back (see there)
        return solid, {"triangles": n, "closed_solid": bool(solid.isValid())}
    out = cq.Shape.cast(shape); out._source_mesh = m
    return out, {"triangles": n, "closed_solid": False}


def clean_body(mesh, cells=150):
    """One closed surface with no inner shells: voxelise, fill, re-skin, smooth. SAM 3D's
    mouse had overlapping shells that split its slices into four loops."""
    vg = mesh.voxelized(max(mesh.extents) / cells).fill()
    mc = vg.marching_cubes
    mc.apply_transform(vg.transform)                 # marching_cubes comes back in cell units
    trimesh.smoothing.filter_taubin(mc, lamb=0.5, nu=-0.53, iterations=15)
    return mc


def solidify(mesh, cells=160, min_cavity=0.3, close_mm=6.5):
    """A scan that is a shell open underneath, filled into the solid it stands for.

    SAM 3D sometimes returns a shell: the mouse came back as walls open at the bottom, 31 cm3
    where the solid is about 190, and that hollow went on into model.stl, the STEP and the
    NURBS. The object rests on the sheet, so any space the object and the sheet enclose
    together is inside it: the sheet is added as a floor, gaps up to `close_mm` are closed,
    enclosed space is filled, and the floor is kept only under what was filled. A mug stays
    open at the top, and the space between a clock's legs stays empty. A mesh whose enclosed
    cavity is under `min_cavity` of its own volume is returned as it is; a filled one is rebuilt
    by marching cubes at `cells` across."""
    from scipy import ndimage
    pitch = float(max(mesh.extents)) / cells
    vox = mesh.voxelized(pitch).fill()
    r = int(np.ceil(close_mm / pitch)); pad = r + 2
    m = np.pad(vox.matrix, pad)
    lo = int(np.argmax(m.any(axis=(0, 1))))         # the lowest occupied layer: the sheet
    floor = m.copy(); floor[:, :, lo] |= ndimage.binary_fill_holes(m.any(axis=2))
    # The mouse's shell also had slits in its side, 1.6 mm wide and 6.2 at most, through which
    # its inside reached the outside; closing first seals gaps up to `close_mm`.
    closed = ndimage.binary_closing(floor, structure=ndimage.iterate_structure(ndimage.generate_binary_structure(3, 1), r))
    filled = ndimage.binary_fill_holes(closed | m)
    filled[:, :, lo] = m[:, :, lo] | (filled[:, :, lo] & filled[:, :, lo + 1])
    # Decide on the enclosed cavity, not the gain: closing also fills the gaps between Mario's
    # arms and body (gain 1.12), which are not enclosed; the mouse's inside is (gain 3.8).
    cavity = (filled & ~closed).sum() / max(m.sum(), 1)
    gain = filled.sum() / max(m.sum(), 1)
    if cavity < min_cavity:
        return mesh, {"filled": False, "cavity": round(float(cavity), 2)}
    vg = trimesh.voxel.VoxelGrid(filled, transform=vox.transform @ trimesh.transformations.translation_matrix([-pad, -pad, -pad]))
    out = vg.marching_cubes
    out.apply_transform(vg.transform)
    trimesh.smoothing.filter_taubin(out, lamb=0.5, nu=-0.53, iterations=15)
    out.apply_translation((0, 0, mesh.bounds[0][2] - out.bounds[0][2]))
    return out, {"filled": True, "cavity": round(float(cavity), 2), "volume_cm3": [round(float(mesh.volume) / 1000, 1), round(float(out.volume) / 1000, 1)]}


def main_body(mesh):
    """The largest connected piece: SAM 3D meshes carry small loose parts (a scroll wheel)."""
    parts = mesh.split(only_watertight=False)
    return max(parts, key=lambda p: p.area) if len(parts) > 1 else mesh


def _circle_of(ring, rel=0.03, floor=0.3):
    """(cx, cy, r) when a closed ring is a circle within max(`floor` mm, `rel` of r), else None."""
    xy = np.asarray(ring)[:-1]
    if len(xy) < 8:
        return None
    A = np.c_[2 * xy, np.ones(len(xy))]
    cx, cy, k = np.linalg.lstsq(A, (xy ** 2).sum(1), rcond=None)[0]
    r = math.sqrt(max(k + cx * cx + cy * cy, 0))
    d = np.hypot(xy[:, 0] - cx, xy[:, 1] - cy)
    return (float(cx), float(cy), float(r)) if np.max(np.abs(d - r)) < max(floor, rel * r) else None


def prismatic_levels(body, step_mm=1.0, change=0.06, max_levels=4):
    """Split a solid into levels whose horizontal outline does not change: a part made of
    stacked extrusions (a bracket, a gear with a hub, a block). Returns [(z0, z1, outline)] in
    the sheet frame, or (None, why). A run of slices shorter than 3% of the height between two
    levels is a transition (the scan rounds the top and bottom edges) and joins its neighbours."""
    from shapely.ops import unary_union
    z0, z1 = float(body.bounds[0][2]), float(body.bounds[1][2])
    n = int(np.clip((z1 - z0) / step_mm, 20, 160))
    zs = z0 + (np.arange(n) + 0.5) / n * (z1 - z0)
    slices = []
    for z in zs:
        sec = body.section(plane_origin=(0, 0, z), plane_normal=(0, 0, 1))
        if sec is None:
            return None, f"no material at {z - z0:.1f} mm"
        g = unary_union(sec.to_planar(to_2D=np.eye(4))[0].polygons_full).buffer(0)
        slices.append(g)
    runs, start = [], 0
    for i in range(1, n + 1):
        if i == n or slices[i].symmetric_difference(slices[start]).area > change * max(slices[start].area, slices[i].area):
            runs.append((start, i)); start = i
    minimum = max(2, int(0.03 * n))
    levels = [r for r in runs if r[1] - r[0] >= minimum]
    if not levels:
        return None, "no level is tall enough"
    if len(levels) > max_levels:
        return None, f"{len(levels)} levels; a prismatic part has at most {max_levels}"
    shapes = [slices[(a + b) // 2] for a, b in levels]
    cuts = [_level_boundary(body, zs[levels[k][1] - 1], zs[levels[k + 1][0]], shapes[k], shapes[k + 1])
            for k in range(len(levels) - 1)]
    edges = [z0] + cuts + [z1]
    return [(edges[k], edges[k + 1], shapes[k].simplify(0.25)) for k in range(len(levels))], None


def _level_boundary(body, lo, hi, below, above, tol=0.05):
    """Where one level becomes the next, between the last slice of the one and the first of the
    other: the height at which a section stops looking like the level below, found by halving
    the gap to `tol` mm. The slices alone put it half a slice out (26.0 for a step at 26.5)."""
    from shapely.ops import unary_union
    while hi - lo > tol:
        z = (lo + hi) / 2
        sec = body.section(plane_origin=(0, 0, z), plane_normal=(0, 0, 1))
        if sec is None:
            break
        g = unary_union(sec.to_planar(to_2D=np.eye(4))[0].polygons_full).buffer(0)
        if g.symmetric_difference(below).area <= g.symmetric_difference(above).area:
            lo = z
        else:
            hi = z
    return (lo + hi) / 2


def prismatic_cad(body, max_off=0.10):
    """Stacked extrusions with true circular holes, and the same part as a feature tree.
    Accepted only when the solid and the extrusions differ by under `max_off` of the volume."""
    levels, why = prismatic_levels(body)
    if levels is None:
        return None, why, None
    solid, steps, params, circles, other_cuts = None, [], [], [], []
    for k, (za, zb, outline) in enumerate(levels):
        params.append({"name": f"level{k + 1}_h", "value": round(float(zb - za), 2), "min": round(float(zb - za) / 2, 2),
                       "max": round(2 * float(zb - za), 2), "what": f"height of level {k + 1}"})
        from_z = round(za - levels[0][0], 2) if k == 0 else " + ".join(f"level{i + 1}_h" for i in range(k))
        polys = [q for q in getattr(outline, "geoms", [outline]) if q.area >= 4]
        for j, poly in enumerate(polys):
            outer = [(float(x), float(y)) for x, y in np.asarray(poly.exterior.coords)[:-1]]
            wires = [cq.Wire.makePolygon([cq.Vector(x, y, za) for x, y in outer], close=True)]
            for ring in poly.interiors:
                c = _circle_of(list(ring.coords))
                if c and c[2] > 0.5:
                    wires.append(cq.Wire.makeCircle(c[2], cq.Vector(c[0], c[1], za), cq.Vector(0, 0, 1)))
                    # One hole through several levels is one feature with one diameter.
                    same = next((h for h in circles if h["last"] == k - 1 and math.hypot(h["c"][0] - c[0], h["c"][1] - c[1]) < 0.6
                                 and abs(h["c"][2] - c[2]) < 0.4), None)
                    if same:
                        same["last"] = k
                    else:
                        circles.append({"c": c, "first": k, "last": k})
                else:
                    pts = [(float(x), float(y)) for x, y in np.asarray(ring.coords)[:-1]]
                    wires.append(cq.Wire.makePolygon([cq.Vector(x, y, za) for x, y in pts], close=True))
                    other_cuts.append((k, pts))
            piece = cq.Solid.extrudeLinear(cq.Face.makeFromWires(wires[0], wires[1:]), cq.Vector(0, 0, zb - za))
            solid = piece if solid is None else solid.fuse(piece)
            steps.append({"id": f"level{k + 1}" + (f"_{j + 1}" if len(polys) > 1 else ""), "op": "extrude", "mode": "add",
                          "shape": {"polygon": [[round(x, 2), round(y, 2)] for x, y in outer]}, "from_z": from_z, "height": f"level{k + 1}_h"})
    z_of = lambda k: "0" if k == 0 else " + ".join(f"level{i + 1}_h" for i in range(k))
    for i, h in enumerate(circles, 1):
        cx, cy, r = h["c"]
        params.append({"name": f"hole{i}_d", "value": round(2 * r, 2), "min": round(r, 2), "max": round(4 * r, 2), "what": f"hole {i} diameter"})
        steps.append({"id": f"hole{i}", "op": "extrude", "mode": "cut", "shape": {"circle": {"d": f"hole{i}_d"}, "at": [round(cx, 2), round(cy, 2)]},
                      "from_z": z_of(h["first"]), "height": " + ".join(f"level{j + 1}_h" for j in range(h["first"], h["last"] + 1))})
    for i, (k, pts) in enumerate(other_cuts, 1):
        steps.append({"id": f"opening{i}", "op": "extrude", "mode": "cut", "shape": {"polygon": [[round(x, 2), round(y, 2)] for x, y in pts]},
                      "from_z": z_of(k), "height": f"level{k + 1}_h"})
    holes = len(circles)
    solid = solid.clean()
    vol = abs(body.volume)
    off = None
    try:
        cad = to_mesh(solid)
        off = trimesh.boolean.difference([body, cad], engine="manifold").volume + trimesh.boolean.difference([cad, body], engine="manifold").volume
        off /= vol
    except Exception:
        off = abs(solid.Volume() / vol - 1)
    info = {"levels": len(levels), "level_heights_mm": [round(float(b - a), 1) for a, b, _ in levels], "holes": holes,
            "off_volume_share": round(float(off), 3)}
    if off > max_off:
        return None, f"stacked extrusions differ by {off:.0%} of the volume", None
    tree = {"features": f"{len(levels)} extruded level(s)" + (f" with {holes} round hole(s)" if holes else ""),
            "parameters": params, "steps": steps}
    return solid, info, tree


def to_cad(mesh, route="freeform"):
    """Returns (solid, kind, info, why_not) trying revolve, stacked extrusions, loft, then mesh. Muse Spark's
    route only lowers the roundness bar for a revolve; the volume check still decides."""
    why = {}
    body = main_body(mesh)
    if route in ("revolved", "freeform"):
        s, info = revolved_cad(body, min_round=0.8 if route == "revolved" else 0.92)
        if s is not None:
            return s, "revolved", info, why
        why["revolved"] = info
    # Stacked extrusions: a bracket, a gear, a block. Its feature tree rides in info["_tree"].
    try:
        s, info, tree = prismatic_cad(body)
    except Exception as e:
        s, info, tree = None, f"{type(e).__name__}: {e}", None
    if s is not None:
        return s, "prismatic", {**info, "_tree": tree}, why
    why["prismatic"] = info
    s, info = lofted_cad(body)
    if s is None and not body.is_watertight or s is None and "more than one piece" in str(info):
        clean = clean_body(body)
        s2, info2 = lofted_cad(clean)
        if s2 is not None:
            return s2, "lofted", {**info2, "remeshed": True}, why
        info = f"{info}; after remeshing: {info2}"
        body = clean
    if s is not None:
        return s, "lofted", info, why
    why["lofted"] = info
    s, info = mesh_cad(body if body.is_watertight else clean_body(body))
    return s, "mesh", info, why


# --- parametric holder ----------------------------------------------------------------------

@dataclass
class HolderParams:
    clearance: float = 0.4     # mm all round the object
    wall: float = 3.0          # mm round the pocket
    floor: float = 2.0         # mm under the object (ten 0.2 mm layers)
    depth_fraction: float = 0.5
    max_depth: float = 30.0
    notch_radius: float = 9.0  # finger notches across the narrow side
    notch_depth: float = 0.6   # share of the pocket depth the notches reach
    top_fillet: float = 1.5    # outer rim, so it is pleasant to hold and does not chip
    lead_in: float = 0.8       # chamfer round the pocket's mouth, so the object finds its way in
    foot_chamfer: float = 0.4  # bottom outer edge, against the first layers' elephant's foot
    outline_tolerance: float = 0.5  # 0.3 kept small creases on the bottle's outer wall


def footprint(mesh, px=0.2):
    """The object's outline seen from above, as one polygon (its silhouette on the paper)."""
    lo = mesh.bounds[0][:2] - 2; hi = mesh.bounds[1][:2] + 2
    w, h = (np.ceil((hi - lo) / px).astype(int) + 1)
    img = np.zeros((h, w), np.uint8)
    uv = np.round((mesh.vertices[:, :2] - lo) / px).astype(np.int32)
    for tri in uv[mesh.faces]:
        cv2.fillConvexPoly(img, tri, 1)
    cs, _ = cv2.findContours(img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea).reshape(-1, 2).astype(float) * px + lo
    return Polygon(c).buffer(0).simplify(0.1)


def smooth_outline(poly, tol=0.5):
    """Clean geometry for a traced outline, never inside it.

    A footprint within 1 mm or 3.5% of a circle becomes a true circle, its radius reaching the
    farthest point. Anything else becomes a smoothing spline (`tol` mm) fitted as an upper
    envelope of the trace. The traced outline carries every voxel and pixel step of the scan; a
    holder cut from it had a visibly lumpy rim (3 Nov 2026).
    Returns ("circle", (cx, cy, r)) or ("curve", polygon)."""
    from scipy.interpolate import splprep, splev
    from shapely.geometry import Point
    xy = np.asarray(poly.exterior.coords)[:-1]
    # Judge everything on points spaced along the outline, not on its vertices: a simplified
    # box keeps only its four corners, and four corners always lie on a circle.
    seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(np.r_[xy, xy[:1]], axis=0), axis=1))]
    t = np.linspace(0, seg[-1], 400, endpoint=False)
    ring = np.c_[np.interp(t, seg, np.r_[xy[:, 0], xy[0, 0]]), np.interp(t, seg, np.r_[xy[:, 1], xy[0, 1]])]
    A = np.c_[2 * ring, np.ones(len(ring))]
    cx, cy, k = np.linalg.lstsq(A, (ring ** 2).sum(1), rcond=None)[0]
    r = np.sqrt(k + cx * cx + cy * cy)
    d = np.hypot(ring[:, 0] - cx, ring[:, 1] - cy)
    # 1 mm or 3.5% of the radius: the bottle's hull sits ±0.7 mm off a circle; the nearest
    # thing that is not round (Mario) is 5 mm off. The radius encloses the whole trace.
    if np.max(np.abs(d - r)) < max(1.0, 0.035 * r):
        return "circle", (float(cx), float(cy), float(max(d.max(), np.hypot(xy[:, 0] - cx, xy[:, 1] - cy).max())))
    # An upper envelope: wherever the trace pokes through the fitted curve, that point's target
    # moves out by the miss and the curve is fitted again, so it moves out only there. Pushing
    # the whole curve out by the worst miss instead gave a box 1.4 mm of clearance on every flat
    # side, because the spline rounds its corners about 1 mm inside.
    target = ring.copy()
    for _ in range(8):
        tck, u = splprep([target[:, 0], target[:, 1]], per=True, s=len(ring) * (tol ** 2) * 0.5)
        sx, sy = splev(np.linspace(0, 1, 800, endpoint=False), tck)
        smooth = Polygon(np.c_[sx, sy]).buffer(0)
        miss = np.array([0.0 if smooth.contains(Point(q)) else smooth.exterior.distance(Point(q)) for q in ring])
        if miss.max() < 0.02:
            break
        cx, cy = splev(u, tck)
        away = ring - np.c_[cx, cy]
        away /= np.maximum(np.linalg.norm(away, axis=1), 1e-9)[:, None]
        target += away * (miss[:, None] + 0.02 * (miss[:, None] > 0))
    poke = float(miss.max())
    out = smooth.buffer(poke + 0.01, join_style=1) if poke > 0 else smooth
    # Never more than `tol` outside the trace either: forced round a sharp corner, a smooth
    # curve bulges out along the sides beside it (a box's pocket came out 1.1 mm too long).
    return "curve", Polygon(out.exterior)


def _even_points(poly, spacing=1.5):
    """Evenly spaced points for an interpolating spline. Spacing them by bend as well, tried on
    3 Nov to keep a box's corners tight, crowded points into small kinks, the spline wobbled
    there, and every edge treatment failed on Mario and the mug."""
    ring = np.asarray(poly.exterior.coords)[:-1]
    seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(np.r_[ring, ring[:1]], axis=0), axis=1))]
    t = np.linspace(0, seg[-1], max(64, int(seg[-1] / spacing)), endpoint=False)
    return [(float(np.interp(s, seg, np.r_[ring[:, 0], ring[0, 0]])), float(np.interp(s, seg, np.r_[ring[:, 1], ring[0, 1]]))) for s in t]


def _wire_polygon(sketch, n=3000):
    """The closed curve CadQuery will actually cut, as a polygon, so checks run on it."""
    w = sketch.val() if hasattr(sketch, "val") else sketch
    w = w if isinstance(w, cq.Wire) else cq.Wire.assembleEdges([w])
    # Edge by edge, by parameter: a Wire rebuilds its curve for every point asked of it, and by
    # length CadQuery measures the arc again each time (minutes on one long spline, 16 ms here).
    edges = w.Edges(); total = sum(e.Length() for e in edges)
    pts = [q[:2] for e in edges for q in _edge_points(e, np.linspace(0, 1, max(8, int(n * e.Length() / total)), endpoint=False))]
    return Polygon(pts)


def _edge_points(e, ts):
    """Points at fractions `ts` of an edge's parameter range (CadQuery's parameter mode takes
    the curve's raw parameter, which for a spline runs over its chord length, not 0 to 1)."""
    ad = e._geomAdaptor(); a, b = ad.FirstParameter(), ad.LastParameter()
    return [q.toTuple() for q in e.positions([a + t * (b - a) for t in ts], mode="parameter")]


def _outside(poly, ring_pts):
    """How far the furthest of `ring_pts` lies outside `poly` (0 when all are inside)."""
    from shapely.geometry import Point
    return max([0.0] + [poly.exterior.distance(Point(q)) for q in ring_pts if not poly.contains(Point(q))])


def _outward(pts):
    pts = np.asarray(pts)
    t = np.roll(pts, -1, 0) - np.roll(pts, 1, 0); t /= np.linalg.norm(t, axis=1)[:, None]
    n = np.c_[t[:, 1], -t[:, 0]]
    if 0.5 * np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1]) < 0:
        n = -n                                        # outward, whichever way the ring runs
    return pts, n


def _ring(q, z):
    return cq.Workplane("XY").spline([tuple(x) for x in q], periodic=True).close().val().translate((0, 0, z))


def _foot_cutter(pts, size, ext=0.3):
    """The 45° chamfer round the bottom edge, built the same way as the lead-in: everything
    outside a ruled loft from `size` inside the outline at the bed to the outline `size` up."""
    pts, n = _outward(pts)
    keep = cq.Solid.makeLoft([_ring(pts - n * (size + ext), -ext), _ring(pts + n * ext, size + ext)], True)
    lo, hi = pts.min(0) - 20, pts.max(0) + 20
    slab = cq.Workplane("XY").box(*(hi - lo), size + 2 * ext + 1, centered=False).translate((lo[0], lo[1], -ext - 1)).val()
    return slab.cut(keep)


def _lead_in_cutter(pts, z, size, ext=0.3):
    """A 45° chamfer round a pocket's mouth, built rather than asked of OpenCascade: its
    chamfer on Mario's spline pocket ran for over five minutes without an answer. A ruled loft
    from the points the pocket's spline passes through to the same points moved out along
    their normals, starting `ext` inside the pocket so no face of it lies on the wall."""
    pts = np.asarray(pts)
    t = np.roll(pts, -1, 0) - np.roll(pts, 1, 0); t /= np.linalg.norm(t, axis=1)[:, None]
    n = np.c_[t[:, 1], -t[:, 0]]
    if 0.5 * np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1]) < 0:
        n = -n                                        # outward, whichever way the ring runs
    ring = lambda q, zz: cq.Workplane("XY").spline([tuple(x) for x in q], periodic=True).close().val().translate((0, 0, zz))
    return cq.Solid.makeLoft([ring(pts - n * ext, z - size - ext), ring(pts + n * (size + ext), z + ext)], True)


def holder_cad(mesh, p=HolderParams(), skip=()):
    """A parametric holder with design for manufacture built in: a smooth outline, a filleted
    rim, a lead-in chamfer round the pocket, a chamfered foot and rounded finger notches.

    Every check runs on the curves CadQuery cuts, not on the polygons they were made from: an
    interpolating spline can swing inside the points it passes through, so the pocket is grown
    until the footprint plus clearance fits inside its own curve."""
    from shapely.geometry import Point
    height = float(mesh.bounds[1][2] - mesh.bounds[0][2])
    depth = min(p.depth_fraction * height, p.max_depth)
    total = p.floor + depth
    foot = footprint(mesh)
    need = np.asarray(foot.buffer(max(p.clearance - 0.05, 0), join_style=1).exterior.coords)
    kind, shape = smooth_outline(foot, p.outline_tolerance)
    if kind == "circle":
        cx, cy, r = shape
        ri, ro = r + p.clearance, r + p.clearance + p.wall
        pocket_sk = cq.Workplane("XY").center(cx, cy).circle(ri)
        outer_sk = cq.Workplane("XY").center(cx, cy).circle(ro)
        pocket, outer = Point(cx, cy).buffer(ri, 256), Point(cx, cy).buffer(ro, 256)
    else:
        sp = lambda pts: cq.Workplane("XY").spline(pts, periodic=True).close()
        grow = 0.0
        for _ in range(4):
            # Closing by 2 mm rounds the inward corners an outward offset sharpens. A chamfer or
            # fillet cannot pass a bend tighter than itself: Mario's pocket had 0.8 mm corners
            # under a 0.8 mm lead-in. It only ever widens the pocket.
            target = shape.buffer(p.clearance + grow + 2, join_style=1).buffer(-2, join_style=1)
            pocket_pts = _even_points(target)
            pocket_sk = sp(pocket_pts)
            pocket = _wire_polygon(pocket_sk)
            miss = _outside(pocket, need)
            if miss <= 0 and pocket.is_valid:
                break
            grow += miss + 0.03
        # The outside only has to be smooth and at least a wall thick: closing it by 3.5 mm
        # turns the inward corners an offset leaves into rounds wider than the rim fillet, and
        # only ever adds material.
        outer_target = target.buffer(p.wall + 3.5, join_style=1).buffer(-3.5, join_style=1)
        outer_pts = _even_points(outer_target)
        outer_sk = sp(outer_pts)
        outer = _wire_polygon(outer_sk)
    body = outer_sk.extrude(total).cut(pocket_sk.extrude(depth + 1).translate((0, 0, p.floor)))
    dfm = {"outline": kind}

    def treat(name, select, op, size):
        nonlocal body
        if name.rsplit("_", 2)[0] in skip:
            dfm[name] = "off"; return
        try:
            edges = [e for e in body.edges().vals() if select(e)]
            if not edges:
                dfm[name] = "no edges"; return
            new = body.newObject(edges)
            new = new.fillet(size) if op == "fillet" else new.chamfer(size)
            if new.val().isValid():
                body = new; dfm[name] = round(size, 2)
            else:
                dfm[name] = "skipped (invalid)"
        except Exception as e:
            dfm[name] = f"skipped ({type(e).__name__})"

    at = lambda e: _edge_points(e, (0.1, 0.5, 0.9))
    off = lambda ring, e: max(ring.exterior.distance(Point(q[0], q[1])) for q in at(e))
    # The rim and the foot while each is still one closed loop, which OpenCascade fillets
    # reliably; a loop broken by notches first failed on two of five holders.
    if kind == "circle" or "lead_in" in skip:
        treat("lead_in_chamfer_mm", lambda e: all(abs(q[2] - total) < 0.05 for q in at(e)) and off(pocket, e) < 0.05, "chamfer", p.lead_in)
    else:
        try:
            new = body.cut(_lead_in_cutter(pocket_pts, total, p.lead_in))
            if new.val().isValid():
                body = new; dfm["lead_in_chamfer_mm"] = p.lead_in
            else:
                dfm["lead_in_chamfer_mm"] = "skipped (invalid)"
        except Exception as ex:
            dfm["lead_in_chamfer_mm"] = f"skipped ({type(ex).__name__})"
    treat("top_fillet_mm", lambda e: all(abs(q[2] - total) < 0.05 for q in at(e)) and off(outer, e) < 0.05, "fillet", min(p.top_fillet, p.wall / 2.2))
    if kind == "circle" or "foot" in skip:
        treat("foot_chamfer_mm", lambda e: all(abs(q[2]) < 0.05 for q in at(e)) and off(outer, e) < 0.05, "chamfer", p.foot_chamfer)
    else:
        try:
            new = body.cut(_foot_cutter(outer_pts, p.foot_chamfer))
            if new.val().isValid():
                body = new; dfm["foot_chamfer_mm"] = p.foot_chamfer
            else:
                dfm["foot_chamfer_mm"] = "skipped (invalid)"
        except Exception as ex:
            dfm["foot_chamfer_mm"] = f"skipped ({type(ex).__name__})"
    # Finger notches: a U scoop through the wall at both ends of the footprint's narrow axis,
    # a horizontal cylinder centred on the rim, so the bottom of the notch is round as cut.
    xy = np.asarray(foot.exterior.coords)
    c = xy.mean(0); _, V = np.linalg.eigh(np.cov((xy - c).T)); minor = V[:, 0]
    proj = (xy - c) @ minor
    r = min(p.notch_radius, depth * p.notch_depth)
    reach = p.clearance + p.wall + 6
    axes = []
    for end in (proj.min(), proj.max()):
        n = c + minor * end
        start = (n[0] - minor[0] * reach, n[1] - minor[1] * reach, total)
        axes.append((np.array(start), np.array([minor[0], minor[1], 0.0])))
        body = body.cut(cq.Workplane(cq.Plane(origin=start, xDir=(0, 0, 1), normal=(minor[0], minor[1], 0)))
                        .circle(r).extrude(2 * reach))
    dfm["notch_mm"] = round(r, 1)

    def on_notch(e):
        for o, d in axes:
            if all(abs(np.linalg.norm(np.cross(np.array(q) - o, d)) - r) < 0.05 for q in at(e)):
                return True
        return False
    # Where a notch crosses the rim fillet and the lead-in OpenCascade often refuses a fillet;
    # then a smaller one, then a chamfer. A notch left sharp still prints and is reported.
    for name, op, size in (("notch_fillet_mm", "fillet", 0.8), ("notch_fillet_mm", "fillet", 0.4), ("notch_chamfer_mm", "chamfer", 0.4)):
        treat(name, on_notch, op, size)
        if not str(dfm[name]).startswith("skipped"):
            break
    solid = body.val()
    bb = solid.BoundingBox()
    wall = min(outer.exterior.distance(Point(q)) for q in pocket.exterior.coords)
    dfm.update({"min_wall_mm": round(wall, 2), "floor_mm": p.floor, "pocket_clear_of_footprint": _outside(pocket, need) == 0,
                "overhangs": "none: the pocket walls are vertical", "supports": "not needed",
                "bed_contact_cm2": round(outer.area / 100, 1)})
    info = {**asdict(p), "pocket_depth_mm": round(depth, 1), "valid": bool(solid.isValid()),
            "holder_mm": [round(bb.xlen, 1), round(bb.ylen, 1), round(bb.zlen, 1)],
            "pocket_outline_mm": [round(pocket.bounds[2] - pocket.bounds[0], 1), round(pocket.bounds[3] - pocket.bounds[1], 1)],
            "dfm": dfm, "volume_cm3": round(solid.Volume() / 1000, 1)}
    return solid, info, pocket, outer


def _holder_child(vertices, faces, p, skip, step_path):
    solid, info, pocket, outer = holder_cad(trimesh.Trimesh(vertices, faces, process=False), p, skip)
    cq.exporters.export(cq.Workplane().add(solid), step_path)
    return info, pocket.wkt, outer.wkt


# Edge treatments that may be dropped, most fragile first. OpenCascade can crash outright on a
# fillet (a notch on a box's holder did, 3 Nov), which would take the web server with it.
_FALLBACKS = ((), ("notch",), ("notch", "top", "lead_in", "foot"))


def holder_cad_safe(mesh, p=HolderParams(), timeout=240):
    """holder_cad in a child process: if a fillet crashes or hangs it, try again without the
    notch fillets, then without any edge treatment, so a scan always gets a holder."""
    import multiprocessing as mp, tempfile
    from concurrent.futures import ProcessPoolExecutor
    from shapely import wkt
    errors = []
    for skip in _FALLBACKS:
        step = tempfile.NamedTemporaryFile(suffix=".step", delete=False).name
        pool = ProcessPoolExecutor(1, mp_context=mp.get_context("spawn"))
        try:
            info, pocket, outer = pool.submit(_holder_child, np.asarray(mesh.vertices), np.asarray(mesh.faces), p, skip, step).result(timeout)
            solid = cq.importers.importStep(step).val()
            info["dfm"]["fallback"] = list(skip) or None
            if errors:
                info["dfm"]["failed_attempts"] = errors
            return solid, info, wkt.loads(pocket), wkt.loads(outer)
        except Exception as e:
            errors.append(f"{'+'.join(skip) or 'all'}: {type(e).__name__}")
        finally:
            for pr in list(getattr(pool, "_processes", {}).values()):
                pr.kill()
            pool.shutdown(wait=False, cancel_futures=True)
            os.remove(step) if os.path.exists(step) else None
    raise RuntimeError("holder failed: " + "; ".join(errors))


def to_mesh(solid, tol=0.05, weld=None):
    """Tessellate a CAD solid for printing, rendering and the fit checks.

    Unless `weld` is given, the first of no weld, 0.02 and 0.05 mm that comes out watertight:
    where the holder's lead-in meets the pocket wall OpenCascade leaves edges of 0.01 to 0.03 mm
    unshared, while welding at 0.05 mm tore the tape holder's notch fillet."""
    from scipy.spatial import cKDTree
    # A solid sewn from triangles is its mesh already. OpenCascade took 140 to 190 s to mesh
    # Mario's 3,000 flat faces again, most of the 319 s the CAD step took in the web app.
    if getattr(solid, "_source_mesh", None) is not None:
        return solid._source_mesh.copy()
    vs, fs = solid.tessellate(tol, 0.2)
    v = np.array([q.toTuple() for q in vs]); f0 = np.array(fs)
    pairs = cKDTree(v).query_pairs(0.05, output_type="ndarray")
    best = None
    for r in ((weld,) if weld is not None else (0.0, 0.02, 0.05)):
        parent = np.arange(len(v))
        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]; i = parent[i]
            return i
        close = pairs[np.linalg.norm(v[pairs[:, 0]] - v[pairs[:, 1]], axis=1) <= r] if r > 0 else pairs[:0]
        for i, j in close:
            ri, rj = root(i), root(j)
            if ri != rj:
                parent[max(ri, rj)] = min(ri, rj)
        f = np.array([[root(i) for i in tri] for tri in f0]) if len(close) else f0.copy()
        f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
        m = trimesh.Trimesh(v, f, process=True)
        m.update_faces(m.unique_faces()); m.remove_unreferenced_vertices()
        if m.is_watertight:
            return m
        best = best or m
    return best


def write_dxf(path, pocket, outer):
    """The holder's top view: pocket and outer outlines, for Bevell's 2D world."""
    import ezdxf
    doc = ezdxf.new(units=4)                      # millimetres
    msp = doc.modelspace()
    for name, poly in (("POCKET", pocket), ("OUTLINE", outer)):
        doc.layers.add(name)
        msp.add_lwpolyline([tuple(map(float, p)) for p in np.asarray(poly.exterior.coords)], close=True, dxfattribs={"layer": name})
    doc.saveas(path)
