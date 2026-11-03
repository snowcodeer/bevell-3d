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
from dataclasses import dataclass, asdict
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
    return (solid, info) if ok else (None, f"loft failed the volume check: {info}")


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


def main_body(mesh):
    """The largest connected piece: SAM 3D meshes carry small loose parts (a scroll wheel)."""
    parts = mesh.split(only_watertight=False)
    return max(parts, key=lambda p: p.area) if len(parts) > 1 else mesh


def to_cad(mesh, route="freeform"):
    """Returns (solid, kind, info, why_not) trying revolve, loft, then mesh. Muse Spark's
    route only lowers the roundness bar for a revolve; the volume check still decides."""
    why = {}
    body = main_body(mesh)
    if route in ("revolved", "freeform"):
        s, info = revolved_cad(body, min_round=0.8 if route == "revolved" else 0.92)
        if s is not None:
            return s, "revolved", info, why
        why["revolved"] = info
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
    floor: float = 2.0         # mm under the object
    depth_fraction: float = 0.5
    max_depth: float = 30.0
    notch_radius: float = 9.0  # finger notches across the narrow side
    notch_depth: float = 0.6   # share of the pocket depth the notches reach
    edge_fillet: float = 1.0


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


def holder_cad(mesh, p=HolderParams()):
    height = float(mesh.bounds[1][2] - mesh.bounds[0][2])
    depth = min(p.depth_fraction * height, p.max_depth)
    foot = footprint(mesh)
    pocket = foot.buffer(p.clearance, join_style=1).simplify(0.05)
    outer = pocket.buffer(p.wall, join_style=1).simplify(0.05)
    total = p.floor + depth

    def spline_face(poly, n=160):
        ring = np.asarray(poly.exterior.coords)[:-1]
        seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(np.r_[ring, ring[:1]], axis=0), axis=1))]
        t = np.linspace(0, seg[-1], n, endpoint=False)
        pts = [(float(np.interp(s, seg, np.r_[ring[:, 0], ring[0, 0]])), float(np.interp(s, seg, np.r_[ring[:, 1], ring[0, 1]]))) for s in t]
        return cq.Workplane("XY").spline(pts, periodic=True).close()

    body = spline_face(outer).extrude(total)
    body = body.cut(spline_face(pocket).extrude(depth + 1).translate((0, 0, p.floor)))
    # Notches at both ends of the footprint's narrow axis, from the rim down.
    xy = np.asarray(foot.exterior.coords)
    c = xy.mean(0); w, V = np.linalg.eigh(np.cov((xy - c).T)); minor = V[:, 0]
    proj = (xy - c) @ minor
    for end in (proj.min(), proj.max()):
        nx, ny = c + minor * end
        cutter = cq.Workplane("XY").circle(p.notch_radius).extrude(depth * p.notch_depth + 1) \
            .translate((nx, ny, total - depth * p.notch_depth))
        body = body.cut(cutter)
    try:
        body = body.faces(">Z").edges().fillet(min(p.edge_fillet, p.wall / 3))
    except Exception:
        pass
    solid = body.val()
    info = {**asdict(p), "pocket_depth_mm": round(depth, 1), "holder_mm": [round(float(v), 1) for v in solid.BoundingBox().toTuple()[3:6]] if False else None,
            "valid": bool(solid.isValid())}
    bb = solid.BoundingBox()
    info["holder_mm"] = [round(bb.xlen, 1), round(bb.ylen, 1), round(bb.zlen, 1)]
    info["pocket_outline_mm"] = [round(pocket.bounds[2] - pocket.bounds[0], 1), round(pocket.bounds[3] - pocket.bounds[1], 1)]
    return solid, info, pocket, outer


def to_mesh(solid, tol=0.05):
    """Tessellate a CAD solid for rendering and the fit checks."""
    # A solid sewn from triangles is its mesh already. OpenCascade took 140 to 190 s to mesh
    # Mario's 3,000 flat faces again, most of the 319 s the CAD step took in the web app.
    if getattr(solid, "_source_mesh", None) is not None:
        return solid._source_mesh.copy()
    vs, fs = solid.tessellate(tol, 0.2)
    return trimesh.Trimesh(np.array([v.toTuple() for v in vs]), np.array(fs), process=True)


def write_dxf(path, pocket, outer):
    """The holder's top view: pocket and outer outlines, for Bevell's 2D world."""
    import ezdxf
    doc = ezdxf.new(units=4)                      # millimetres
    msp = doc.modelspace()
    for name, poly in (("POCKET", pocket), ("OUTLINE", outer)):
        doc.layers.add(name)
        msp.add_lwpolyline([tuple(map(float, p)) for p in np.asarray(poly.exterior.coords)], close=True, dxfattribs={"layer": name})
    doc.saveas(path)
