"""Gripper fingers that let the SO-101 hold a hand tool and work it.

Scissors or pliers lie flat on the sheet. Their two handles are found in the scan's outline seen
from above (finger loops filled): along the tool's long axis, the handle end is where a line
across it meets two separate pieces. At the grasp line, where the handles are widest (the middle
of a scissors loop, the middle of a pliers handle), each handle gets a saddle: a block whose
groove fits the outer half of that handle, with lips above and below, a flat back that sits on
the inside of one jaw, and notches for two zip ties that go round jaw, saddle and handle (through
the loop on scissors). With both handles tied in, the gripper's own close and open closes and
opens the tool; the ties' give lets the jaw's arc differ from the tool's pivot.

    python -m bevell3d.tool_fingers <scan dir>    # writes tool_fingers.{3mf,stl,step,json} there

The handle's cross-section is a rounded rectangle of its measured width and thickness: a scan is
good to about a millimetre, and the ties take up the rest.
"""
import json, math, os
from dataclasses import dataclass, asdict
import numpy as np
import trimesh
import cadquery as cq
import cv2
from shapely.geometry import LineString, Polygon
from .cad import footprint, to_mesh


@dataclass
class FingerParams:
    length: float = 24.0        # along the handle
    back: float = 3.0           # behind the groove, against the jaw
    lip: float = 2.4            # above and below the handle
    clearance: float = 0.3      # round the handle in the groove
    tie: float = 4.6            # zip-tie notch width (a 3.6 mm tie)
    tie_depth: float = 1.2
    min_handle: float = 3.0     # narrower than this is not a handle
    max_handle: float = 40.0


def _polygon_with_holes(img, to_xy, min_hole_px=30):
    """The largest outline in a binary image, with its holes, mapped through `to_xy`."""
    cs, hier = cv2.findContours(img.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    best = None
    for i, c in enumerate(cs):
        if hier[0][i][3] != -1 or len(c) < 8:
            continue
        holes = [to_xy(cs[j].reshape(-1, 2)) for j in range(len(cs)) if hier[0][j][3] == i and cv2.contourArea(cs[j]) > min_hole_px]
        poly = Polygon(to_xy(c.reshape(-1, 2)), holes).buffer(0)
        if best is None or poly.area > best.area:
            best = poly
    return best


def mesh_outline(mesh, px=0.2):
    """The mesh seen from straight above, holes included (the finger loops of scissors)."""
    lo = mesh.bounds[0][:2] - 2; hi = mesh.bounds[1][:2] + 2
    w, h = (np.ceil((hi - lo) / px).astype(int) + 1)
    img = np.zeros((h, w), np.uint8)
    for tri in np.round((mesh.vertices[:, :2] - lo) / px).astype(np.int32)[mesh.faces]:
        cv2.fillConvexPoly(img, tri, 1)
    return _polygon_with_holes(img, lambda c: c.astype(float) * px + lo).simplify(0.1)


def top_outline(views, masks, z, n=2):
    """The tool's outline from the photos taken most nearly straight down, holes included, on the
    plane `z` mm above the sheet: each mask back-projected through its camera, then the views
    intersected. One view off the vertical sees the outline a little large and the loops a little
    small (their walls hide some of the hole); views from opposite sides cancel that. A photo's
    mask is good to a fifth of a millimetre here, where the scan's voxels are 0.75 mm."""
    ranked = []
    for v, m in zip(views, masks):
        R, _ = cv2.Rodrigues(v["rv"]); C = (-R.T @ np.asarray(v["tv"]).reshape(3)).ravel()
        ranked.append((-(R.T @ np.array([0, 0, 1.0]))[2], v, m, R, C))
    ranked.sort(key=lambda r: -r[0])
    # Only views that look nearly straight down (within about 25 degrees): one is enough, two from
    # opposite sides cancel a little perspective; a 45-degree view would eat into the outline.
    overhead = [r for r in ranked if r[0] > 0.9] or ranked[:1]
    out = None
    for _, v, m, R, C in overhead[:n]:
        Kinv = np.linalg.inv(v["K"])
        def to_xy(c, R=R, C=C, Kinv=Kinv):
            d = (R.T @ (Kinv @ np.c_[c.astype(float), np.ones(len(c))].T)).T
            return C[:2] + d[:, :2] * ((z - C[2]) / d[:, 2])[:, None]
        poly = _polygon_with_holes(m, to_xy)
        out = poly if out is None else out.intersection(poly)
    return max(getattr(out, "geoms", [out]), key=lambda g: g.area).simplify(0.1)


def _intervals(fp, p, perp):
    """Where a line across the footprint through `p` crosses it: [(lo, hi)] along `perp`, in order."""
    g = LineString([p - perp * 400, p + perp * 400]).intersection(fp)
    segs = [g] if g.geom_type == "LineString" else [q for q in getattr(g, "geoms", []) if q.geom_type == "LineString"]
    out = []
    for s in segs:
        if s.length < 0.8:
            continue
        t = sorted(float((np.array(q) - p) @ perp) for q in s.coords)
        out.append((t[0], t[-1]))
    return sorted(out)


def handles(mesh, p=FingerParams(), n=121, outline=None):
    """The two handles at the grasp line, in the sheet frame: their centres, widths, thicknesses
    and directions, the long axis, and the squeeze axis across them. `outline` (with holes) gives
    the part of each handle to grip: on scissors the outer side of the finger loop, the tie going
    through the hole. Raises ValueError for a shape with no two handles side by side."""
    holed = outline if outline is not None else mesh_outline(mesh)
    fp = Polygon(holed.exterior)
    rect = np.array(fp.minimum_rotated_rectangle.exterior.coords)[:4]
    e = [rect[1] - rect[0], rect[2] - rect[1]]
    ax = max(e, key=np.linalg.norm); L = float(np.linalg.norm(ax)); ax = ax / L
    perp = np.array([-ax[1], ax[0]])
    c0 = rect.mean(0)
    found = []
    for s in np.linspace(-0.47, 0.47, n):
        q = c0 + ax * s * L
        iv = _intervals(fp, q, perp)
        fused = False
        if len(iv) == 1 and outline is not None:
            # Loops that touch: one shape from above with two finger holes. Split at the middle
            # of the wall they share.
            ii = _intervals(holed, q, perp)
            if len(ii) == 3:
                mid = 0.5 * (ii[1][0] + ii[1][1])
                iv, fused = [(ii[0][0], mid), (mid, ii[2][1])], True
        if len(iv) != 2:
            continue
        w = [b - a for a, b in iv]
        gap = iv[1][0] - iv[0][1]
        if (gap < 1.5 and not fused) or not all(p.min_handle <= x <= p.max_handle for x in w):
            continue
        found.append((s, q, iv, w))
    if not found:
        raise ValueError("No two handles side by side: lay the tool flat, closed, with both handles on the sheet.")
    # The handles are on one side of the tool; keep the longest run of positions that have them.
    sides = [np.sign(f[0]) for f in found]
    side = max((-1, 1), key=lambda sg: sum(1 for x in sides if x == sg))
    run = [f for f in found if np.sign(f[0]) == side]
    s_mid = np.median([f[0] for f in run])
    # Lines that cross both finger holes, when any do: on a pair whose loops nearly touch in the
    # middle the only gap between the handles is at the loops' far ends, past the holes, and the
    # widest line there found no loops at all.
    def _both_loops(f):
        inner_f = _intervals(holed, f[1], perp)
        return all(len([(a, b) for a, b in inner_f if b > lo + 0.3 and a < hi - 0.3]) >= 2 for lo, hi in f[2])
    looped = [f for f in run if _both_loops(f)]
    if looped:
        run = looped
        s_mid = np.median([f[0] for f in run])
    # Widest pair (the loops' middles), nudged towards the middle of the run (pliers' handles
    # are about as wide all along).
    s, q, iv, w = max(run, key=lambda f: sum(f[3]) - 0.03 * abs(f[0] - s_mid) * L)
    out = []
    inner = _intervals(holed, q, perp)
    for k in range(2):
        lo, hi = iv[k]
        # The part to grip: the outermost piece of this handle on the line (a loop's outer ring).
        mine = [(max(a, lo), min(b, hi)) for a, b in inner if b > lo + 0.3 and a < hi - 0.3]
        loop = len(mine) >= 2
        if mine:
            lo, hi = mine[0] if k == 0 else mine[-1]
        w[k] = hi - lo
        mid = (lo + hi) / 2
        centre = q + perp * mid
        # The handle's own direction: its centre a little either side of the grasp line.
        pts = []
        for ds in (-0.04, 0.04):
            q2 = c0 + ax * (s + ds) * L
            iv2 = _intervals(fp, q2, perp)
            if len(iv2) == 2:
                pts.append(q2 + perp * (iv2[k][0] + iv2[k][1]) / 2)
        d = (pts[1] - pts[0]) if len(pts) == 2 else ax
        d = d / np.linalg.norm(d)
        if d @ ax < 0:
            d = -d
        near = np.linalg.norm(mesh.vertices[:, :2] - centre, axis=1) < max(3.0, w[k] / 2)
        z = mesh.vertices[near, 2] if near.any() else mesh.vertices[:, 2]
        out.append({"centre_mm": centre.round(2).tolist(), "width_mm": round(float(w[k]), 2),
                    "thickness_mm": round(float(z.max() - max(0.0, z.min())), 2), "z_mm": round(float(z.min()), 2),
                    "direction": d.round(4).tolist(), "loop": loop,
                    "angle_deg": round(math.degrees(math.atan2(d @ perp, d @ ax)), 1)})
    return {"long_axis": ax.round(4).tolist(), "squeeze_axis": perp.round(4).tolist(), "length_mm": round(L, 1),
            "grasp_line_mm": q.round(2).tolist(), "gap_mm": round(float(iv[1][0] - iv[0][1]), 2), "handles": out}


def saddle(h, p=FingerParams(), extra=0.0):
    """One saddle in its own frame: x along the jaw, y from the jaw's face towards the tool, z up.
    The back (y = 0) sits on the jaw; the groove holds the outer half of the handle, turned to the
    handle's own angle; zip-tie notches cross the back, top and bottom."""
    w, t = h["width_mm"], h["thickness_mm"]
    gw, gt = w + 2 * p.clearance, t + 2 * p.clearance
    depth = p.back + w / 2                     # to the handle's centre line
    height = gt + 2 * p.lip
    L = p.length + extra                       # a rail: longer, so the loop can slide along it
    block = cq.Workplane("XY").box(L, depth, height, centered=(True, False, False))
    r = max(0.4, 0.25 * min(gw, gt))
    groove = (cq.Workplane("YZ").center(p.back + w / 2, height / 2).rect(gw, gt).extrude(p.length * 3, both=True)
              .edges("|X").fillet(r))
    groove = groove.rotate((0, p.back + w / 2, 0), (0, p.back + w / 2, 1), h.get("tilt_deg", 0.0))
    body = block.cut(groove)
    for sx in (-1, 1):                         # two ties, 4 mm in from each end
        x = sx * (L / 2 - 4 - p.tie / 2)
        for cut in (cq.Workplane("XY").box(p.tie, p.tie_depth, height + 2, centered=(True, False, True)).translate((x, 0, height / 2)),
                    cq.Workplane("XY").box(p.tie, depth + 2, p.tie_depth, centered=(True, False, False)).translate((x, -1, height - p.tie_depth)),
                    cq.Workplane("XY").box(p.tie, depth + 2, p.tie_depth, centered=(True, False, False)).translate((x, -1, 0))):
            body = body.cut(cut)
    return body.val(), {"length_mm": round(L, 1), "depth_mm": round(depth, 2), "height_mm": round(height, 2),
                        "groove_mm": [round(gw, 2), round(gt, 2)]}


def tool_fingers(mesh, p=FingerParams(), outline=None, rail=None):
    """Both saddles, laid out for printing (back down, side by side), and placed on the tool for a
    preview; and the report."""
    info = handles(mesh, p, outline=outline)
    perp = np.array(info["squeeze_axis"]); ax = np.array(info["long_axis"])
    mid = np.mean([np.array(h["centre_mm"]) for h in info["handles"]], axis=0)
    prints, placed, rep = [], [], []
    clips = False                               # scissors get snap clips in custom jaws (custom_jaws.py)
    for k, h in enumerate(info["handles"]):
        out_dir = -1 if k == 0 else 1          # handle 0 lies on the -perp side of the line
        h = {**h, "tilt_deg": h["angle_deg"]}
        solid, dims = saddle(h, p, rail["rail_mm"] if rail and rail.get("moving_handle") == k else 0.0)
        # Print: back face (y = 0) down on the bed, so the groove opens upwards with no overhang.
        lay = solid.rotate((0, 0, 0), (1, 0, 0), 90).translate((0, k * (dims["height_mm"] + 6), 0))
        bb = lay.BoundingBox(); prints.append(lay.translate((0, 0, -bb.zmin)))
        # Preview: on the tool, its back towards the outside of the handle.
        c = np.array(h["centre_mm"]); edge = c + perp * out_dir * (h["width_mm"] / 2 + p.back)
        ang = math.degrees(math.atan2(ax[1], ax[0]))
        s = solid.rotate((0, 0, 0), (0, 0, 1), 180 if out_dir > 0 else 0)   # y now points at the tool's middle
        s = s.rotate((0, 0, 0), (0, 0, 1), ang)
        placed.append(s.translate((edge[0], edge[1], h["z_mm"] - p.lip - p.clearance)))
        rep.append({**{k2: h[k2] for k2 in ("width_mm", "thickness_mm", "angle_deg", "centre_mm", "loop")}, "saddle": dims})
    outer = abs(np.diff([(np.array(h["centre_mm"]) - mid) @ perp for h in info["handles"]])[0]) + sum(h["width_mm"] for h in info["handles"]) / 2
    report = {"tool": {k: info[k] for k in ("length_mm", "gap_mm", "long_axis", "squeeze_axis", "grasp_line_mm")},
              "kind": "snap clips" if clips else "saddles", "saddles": rep, "params": asdict(p),
              "jaw_gap_tool_closed_mm": round(float(outer + 2 * (1.6 + 3.0 if clips else p.back)), 1),
              "fit": ["Tape each saddle's flat back to the inside of a jaw, near its tip, the groove facing the other jaw.",
                      "Close the gripper to the jaw gap above, lay the tool's handles in the grooves, and zip-tie each handle to its saddle and jaw through the notches (through the finger loop on scissors).",
                      "Opening the gripper now opens the tool; closing it closes the tool. Teach the cut with the leader arm and replay it."]}
    return prints, placed, report


def write_tool_fingers(out_dir, mesh, p=FingerParams(), outline=None, rail=None):
    prints, placed, report = tool_fingers(mesh, p, outline, rail)
    if rail:
        report["moving_jaw_saddle"] = rail["moving_handle"]
    report["outline_from"] = "photos from above" if outline is not None else "the scan"
    both = cq.Compound.makeCompound(prints)
    cq.exporters.export(cq.Workplane().add(both), os.path.join(out_dir, "tool_fingers.step"))
    m = trimesh.util.concatenate([to_mesh(s) for s in prints])
    m.export(os.path.join(out_dir, "tool_fingers.stl")); m.export(os.path.join(out_dir, "tool_fingers.3mf"))
    trimesh.util.concatenate([to_mesh(s) for s in placed]).export(os.path.join(out_dir, "tool_fingers_on_tool.stl"))
    json.dump(report, open(os.path.join(out_dir, "tool_fingers.json"), "w"), indent=1)
    return report


if __name__ == "__main__":
    import sys
    import pickle
    d = sys.argv[1]
    src = next(f for f in ("hull.stl", "model.stl") if os.path.exists(os.path.join(d, f)))
    mesh = trimesh.load(os.path.join(d, src))
    outline = None
    if os.path.exists(os.path.join(d, "views.pkl")):         # a scan: the outline from its photos from above
        vp = pickle.load(open(os.path.join(d, "views.pkl"), "rb"))
        outline = top_outline(vp["views"], vp["masks"], float(mesh.bounds[1][2]) / 2)
    print(json.dumps(write_tool_fingers(d, mesh, outline=outline), indent=1))
