"""A custom gripper end for a pair of scissors: new SO-101 jaw parts, the stock fingers gone and the
scissors' holders in their place.

    python -m bevell3d.custom_jaws <scan dir> [--video sim.mp4]

The SO-101's moving jaw turns about the gripper servo's hinge. Stand the scissors with their pivot
on that same axis, in a plane just beside the gripper, and the moving jaw turns the moving blade
about the axis it turns about itself: the blades open exactly as far as the gripper does, with no
slack anywhere. So each finger loop gets a clip that snaps round its ring (the ring's own curve,
from the photos from above), joined by an arm to the part that drives it: one to the moving jaw
(The Robot Studio's Moving_Jaw_SO101), one to the wrist-roll follower that carries the fixed jaw
(Wrist_Roll_Follower_SO101). Gripper closed is scissors closed. The two new parts replace the
originals; everything is meshes joined with Manifold, so they come out watertight.

Frames: the gripper frame of so101_new_calib.xml, in mm. Its fingertips are about 100 mm down
(-z), the jaws close along x, and the moving jaw turns about an axis along y through H.
"""
import argparse, json, math, os, pickle
import numpy as np
import trimesh
from shapely.geometry import Point, Polygon
from .tool_fingers import handles, mesh_outline, top_outline, FingerParams
from .scissors_sim import pivot_of

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "third_party", "so101")
H = np.array([20.2, 18.8, -23.4])                       # the gripper hinge, gripper frame (mm)
JAW_Q = np.array([0.707107, 0.707107, 0.0, 0.0])        # moving jaw body orientation at q = 0
FIXED_POS, MOVING_POS = np.array([0.0, -0.218214, 0.949706]), np.array([0.0, 0.0, 18.9])
FIXED_CUT_Z = -42.0      # gripper frame, mm: below this the wrist-roll follower is only its fixed finger
HUB_R = 26.0             # mm from the hinge: the moving jaw's hub round the servo horn


def _quat_mat(q):
    w, x, y, z = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def fixed_to_gripper():
    """Wrist_Roll_Follower part coordinates (mm) -> gripper frame: the geom's quat (0 1 0 0)."""
    T = np.eye(4); T[:3, :3] = _quat_mat([0, 1, 0, 0]); T[:3, 3] = FIXED_POS
    return T


def moving_to_gripper(q):
    """Moving_Jaw part coordinates (mm) -> gripper frame with the gripper at angle q (rad)."""
    Rq = np.array([[math.cos(q), -math.sin(q), 0], [math.sin(q), math.cos(q), 0], [0, 0, 1]])
    T = np.eye(4); T[:3, :3] = _quat_mat(JAW_Q) @ Rq; T[:3, 3] = H + _quat_mat(JAW_Q) @ Rq @ MOVING_POS
    return T


def _extrude(poly, z0, z1):
    parts = []
    for g in getattr(poly, "geoms", [poly]):
        if g.is_empty or g.area < 0.05:
            continue
        for piece in getattr(g.buffer(0), "geoms", [g.buffer(0)]):
            m = trimesh.creation.extrude_polygon(piece.simplify(0.03), z1 - z0)
            m.apply_translation((0, 0, z0)); parts.append(m)
    return trimesh.boolean.union(parts, engine="manifold") if len(parts) > 1 else parts[0]


def loop_clip_mesh(outline, h, p=FingerParams(), span=None, wall=1.8, lip=0.5, lip_width=1.2, arm_top=True):
    """A clip that snaps round one finger-loop ring, in the sheet frame: the ring's stretch round
    the grasp point (its own curve) inside a channel with a `wall` mm wall, open on the hole side.
    The ring goes in from the hole side and is held by one lip, on the wall away from the arm
    (`arm_top`: the arm joins the clip's top face), narrowing the mouth to `lip` mm less than the ring's thickness:
    the arm stiffens the wall it joins, so only the other can flex. The lip has a stepped lead-in,
    so the mouth starts wider than the ring and narrows to the lip. Returns the clip, its report
    and a keep-out (the channel, the mouth and the hole in front of it) that nothing added later
    may fill."""
    c = np.array(h["centre_mm"]); t = h["thickness_mm"]; z0 = h["z_mm"]; cl = p.clearance
    holes = [Polygon(r) for r in outline.interiors if Polygon(r).area > 20]
    hole = min(holes, key=lambda g: g.distance(Point(c)))
    if span is None:                                   # half the loop's length: a C round the end, not a blob
        e = np.array(hole.minimum_rotated_rectangle.exterior.coords)[:4]
        span = float(np.clip(0.5 * max(np.linalg.norm(e[1] - e[0]), np.linalg.norm(e[2] - e[1])), 10.0, 24.0))
    ring = outline.intersection(hole.buffer(h["width_mm"] + 3.0)).difference(hole)
    window = Point(c).buffer(span / 2, 64)
    ring_w = ring.intersection(window)
    inner = hole.buffer(-lip_width, 32)                # the mouth's face, inside the hole
    footprint = ring_w.buffer(wall, 32).intersection(window.buffer(wall)).difference(inner)
    body = _extrude(footprint, z0 - wall, z0 + t + wall)
    channel = _extrude(ring_w.buffer(cl, 32), z0 - cl, z0 + t + cl)
    band = footprint.difference(ring_w.buffer(cl, 32)).intersection(hole.buffer(cl + 0.05, 32))
    # The lip on the free wall only, its height from the channel's floor: the clearance either side
    # plus the snap, so the mouth is `lip` narrower than the ring (the arm-side wall stays flush).
    lip_h = 2 * cl + lip
    lo_lip, hi_lip = (lip_h, 0.0) if arm_top else (0.0, lip_h)
    cuts = [channel]
    if not band.is_empty and band.area > 0.05:
        # The mouth, in three steps from the hole inwards: wider than the ring, half the lip, the lip.
        for frac, k in ((1 / 3, 1.0), (2 / 3, 0.5), (1.0, 0.0)):
            near = band.intersection(inner.buffer(lip_width * frac + 0.05, 32))
            if near.is_empty or near.area < 0.05:
                continue
            lo = z0 - cl + lo_lip * (1 - k)
            hi = z0 + t + cl - hi_lip * (1 - k)
            cuts.append(_extrude(near, lo, hi))
    body = trimesh.boolean.difference([body] + cuts, engine="manifold")
    # Kept clear for the ring's way in: the channel, the mouth and the hole in front of it.
    front = inner.intersection(window.buffer(wall + 3.0))
    keep = [channel] + cuts[1:]
    if not front.is_empty and front.area > 0.05:
        keep.append(_extrude(front, z0 - cl, z0 + t + cl))
    keepout = trimesh.boolean.union(keep, engine="manifold") if len(keep) > 1 else keep[0]
    return body, {"span_mm": round(span, 1), "wall_mm": wall, "snap_lip_mm": lip, "snap_side": "one wall, away from the arm",
                  "opening_mm": round(t - lip, 2), "lead_in_mm": round(t + 2 * cl, 2),
                  "ring_mm": [h["width_mm"], t]}, keepout


ROUND_MM = 2.0      # every edge of an arm is rounded to this radius
PATCH_FRAC, PATCH_MAX_MM = 0.35, 6.0  # the arm's base on the jaw: wider bases met the other jaw as it turned


def _rounded_hull(pts, r=ROUND_MM):
    """The convex hull of `pts` with every edge and corner rounded to `r`: the hull of a sphere at
    each vertex of the hull shrunk by `r` towards its centre (a Minkowski sum, near enough)."""
    core = trimesh.convex.convex_hull(pts)
    v = core.vertices; ctr = core.centroid
    d = v - ctr; n = np.linalg.norm(d, axis=1, keepdims=True) + 1e-9
    v = ctr + d * np.clip((n - r) / n, 0.2, 1.0)
    ball = trimesh.creation.icosphere(subdivisions=2, radius=r).vertices
    return trimesh.convex.convex_hull((v[:, None, :] + ball[None, :, :]).reshape(-1, 3))


def _arm(clip, part, toward, thickness=6.0, depth=3.0):
    """A solid arm from a clip to a part, every edge rounded: the hull of the clip's face that looks
    at the part and the part's own surface where it faces the clip, within a patch as wide as the
    clip's face, each point of it sunk into the part as far as the material stays solid (up to
    `depth` mm, so never into the servo's pocket). Built on the part's real surface, the arm sits
    flush on the face it meets; a square patch aimed at the nearest point met a corner of the
    housing on one edge only."""
    pts = clip.vertices
    d = pts @ toward
    face = pts[d > d.max() - 0.6]                      # the clip's face that looks at the part
    centre = face.mean(0)
    target, dist, _ = trimesh.proximity.closest_point(part, [centre])
    target = target[0]
    n = (target - centre) / (np.linalg.norm(target - centre) + 1e-9)
    span = np.ptp(face, axis=0); r = max(3.0, min(PATCH_MAX_MM, PATCH_FRAC * float(np.sort(span)[-2])))
    V, N = part.vertices, part.vertex_normals
    pick = (np.linalg.norm(V - target, axis=1) < r) & ((N @ -n) > 0.25)
    if pick.sum() < 4:                                 # no facing surface near: the old square patch
        a = np.cross(n, [0, 0, 1.0]); a = a if np.linalg.norm(a) > 0.1 else np.cross(n, [1.0, 0, 0]); a /= np.linalg.norm(a)
        b = np.cross(n, a)
        base = np.array([target + n * 2.0 + a * sa * r + b * sb * (thickness * 0.75) for sa in (-1, 1) for sb in (-1, 1)])
        return _rounded_hull(np.vstack([face, base])), float(dist[0])
    P, PN = V[pick], N[pick]
    if len(P) > 600:
        k = np.random.default_rng(0).choice(len(P), 600, replace=False); P, PN = P[k], PN[k]
    sunk = P.copy(); ok = np.ones(len(P), bool)
    for frac in (1 / 3, 2 / 3, 1.0):                   # as deep as every step stays inside
        q = P - PN * depth * frac
        ok &= part.contains(q)
        sunk[ok] = q[ok]
    return _rounded_hull(np.vstack([face, P, sunk])), float(dist[0])


def design(scan_dir, side=-1.0, gap=4.0, loops_forward=True, flip=False, p=FingerParams()):
    """Both new parts (part coordinates, mm), the scissors halves (gripper frame) and a report."""
    src = next(f for f in ("hull.stl", "model.stl") if os.path.exists(os.path.join(scan_dir, f)))
    mesh = trimesh.load(os.path.join(scan_dir, src))
    outline = None
    if os.path.exists(os.path.join(scan_dir, "views.pkl")):
        vp = pickle.load(open(os.path.join(scan_dir, "views.pkl"), "rb"))
        outline = top_outline(vp["views"], vp["masks"], float(mesh.bounds[1][2]) / 2)
    outline = outline if outline is not None else mesh_outline(mesh)
    info = handles(mesh, p, outline=outline)
    if not all(h["loop"] for h in info["handles"]):
        raise ValueError("Custom jaws are for scissors: both handles need a finger loop.")
    pivot, toward = pivot_of(outline, info)
    # The pivot screw or rivet in the photo from above, when there is one: the outline's guess
    # (where the two handles join) missed a real pair's screw by 63 mm, because its clear handle
    # joins both loops in the middle.
    from .tool_geometry import find_pivot, tool_thickness, flat_model
    t = tool_thickness(info)
    pivot_how = {"how": "where the handles join (no screw circle found)"}
    if os.path.exists(os.path.join(scan_dir, "views.pkl")):
        found, how = find_pivot(scan_dir, outline, info, t)
        if found is not None:
            pivot, pivot_how = np.asarray(found, float), how
    # What the preview and the simulation show: SAM 3D's model when the scan made one (it keeps
    # the thin blades), else the outline extruded to the measured thickness.
    shown = os.path.join(scan_dir, "sam3d_fitted.stl")
    from .tool_geometry import shown_model
    mesh = shown_model(outline, info, pivot, toward, trimesh.load(shown) if os.path.exists(shown) else None)
    u = -toward                                          # pivot -> loops, in the sheet plane
    v = np.array([-u[1], u[0]])
    fixed = trimesh.load(os.path.join(ROOT, "assets", "wrist_roll_follower_so101_v1.stl")); fixed.apply_scale(1000)
    moving = trimesh.load(os.path.join(ROOT, "assets", "moving_jaw_so101_v1.stl")); moving.apply_scale(1000)
    Tf, Tm0 = fixed_to_gripper(), moving_to_gripper(0.0)
    fixed_g = fixed.copy().apply_transform(Tf); moving_g = moving.copy().apply_transform(Tm0)
    # The stock fingers go: the scissors are the fingers now. The wrist-roll follower keeps its
    # servo housing and mount (above FIXED_CUT_Z; below it is only the fixed finger), the moving jaw
    # its hub round the servo horn (within HUB_R of the hinge; beyond it is only the finger).
    keep = trimesh.creation.box(bounds=[[-80, -80, FIXED_CUT_Z], [80, 80, 40]])
    fixed_g = trimesh.boolean.intersection([fixed_g, keep], engine="manifold")
    hub = trimesh.creation.cylinder(radius=HUB_R, height=120, sections=96)
    hub.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], [0, 1, 0])); hub.apply_translation(H)
    moving_g = trimesh.boolean.intersection([moving_g, hub], engine="manifold")
    # The scissors' plane: beside the gripper, `gap` mm clear of everything on that side.
    edge = min(fixed_g.bounds[0][1], moving_g.bounds[0][1]) if side < 0 else max(fixed_g.bounds[1][1], moving_g.bounds[1][1])
    y_mid = edge + side * (gap + 1.8 + t / 2)
    U = np.array([1.0 if loops_forward else -1.0, 0, 0]); V = np.array([0, 0, -1.0 if flip else 1.0])
    W = np.cross(U, V)                                   # right-handed: the sheet's up is W
    def sheet_to_g():
        M = np.eye(4)
        # sheet (x, y, z) -> scissors (u, v, w) -> gripper
        A = np.c_[np.r_[u, 0], np.r_[v, 0], [0, 0, 1.0]].T  # rows: u, v, z
        R = np.c_[U, V, W] @ A
        M[:3, :3] = R
        M[:3, 3] = np.array([H[0], 0, H[2]]) - R @ np.r_[pivot, 0] + W * (-t / 2 - mesh.bounds[0][2]) + np.array([0, 0, 0])
        M[1, 3] += 0.0
        return M
    S = sheet_to_g()
    # Put the scissors' middle plane at y_mid.
    probe = S @ np.r_[pivot, mesh.bounds[0][2] + t / 2, 1]
    S[:3, 3] += np.array([0, y_mid - probe[1], 0])
    clips, reps, keepouts = [], [], []
    arm_top = bool(W @ np.array([0, -side, 0]) > 0)       # the arms join the clips' top faces
    for h in info["handles"]:
        c, d, k = loop_clip_mesh(outline, h, p, arm_top=arm_top)
        clips.append(c.copy().apply_transform(S)); reps.append(d); keepouts.append(k.copy().apply_transform(S))
    # Which loop the moving jaw drives: turning it with the jaw (about H along -y, the opening
    # sense) must take it away from the other loop.
    cen = [cl.centroid for cl in clips]
    def turn(pt, a):
        Tm = moving_to_gripper(a) @ np.linalg.inv(Tm0)
        return (Tm @ np.r_[pt, 1])[:3]
    grow = [np.linalg.norm(turn(cen[k], 0.2) - cen[1 - k]) - np.linalg.norm(cen[k] - cen[1 - k]) for k in (0, 1)]
    km = int(np.argmax(grow))
    # Arms, then each clip joined to its part (in the gripper frame at q = 0), back to part coordinates.
    arm_m, dm = _arm(clips[km], moving_g, np.array([0, -side, 0]))
    arm_f, df = _arm(clips[1 - km], fixed_g, np.array([0, -side, 0]))
    # Then each part has its loop's way in cut clear again: the rounded arm must not reach into it.
    new_moving = trimesh.boolean.union([moving_g, clips[km], arm_m], engine="manifold")
    new_moving = trimesh.boolean.difference([new_moving, keepouts[km]], engine="manifold").apply_transform(np.linalg.inv(Tm0))
    new_fixed = trimesh.boolean.union([fixed_g, clips[1 - km], arm_f], engine="manifold")
    new_fixed = trimesh.boolean.difference([new_fixed, keepouts[1 - km]], engine="manifold").apply_transform(np.linalg.inv(Tf))
    # The scissors halves for the simulation: the scan cut down the middle (v = 0), in the gripper frame.
    sc = mesh.copy().apply_transform(S)
    pv = (S @ np.r_[pivot, mesh.bounds[0][2] + t / 2, 1])[:3]
    halves = {}
    for k, nrm in ((km, None), (1 - km, None)):
        pass
    side_of = lambda pt: float((pt - pv) @ V)
    sm, sf = side_of(cen[km]), side_of(cen[1 - km])
    half_m = sc.slice_plane(pv, V * np.sign(sm), cap=True)
    half_f = sc.slice_plane(pv, V * np.sign(sf), cap=True)
    report = {"pivot_on_hinge": True, "pivot_found": pivot_how, "scissors_plane_y_mm": round(float(y_mid), 1), "loops": "forward" if loops_forward else "back",
              "side": "left" if side < 0 else "right", "flipped": flip,
              "moving_loop": km, "arm_mm": {"moving": round(dm, 1), "fixed": round(df, 1)}, "clips": reps,
              "parts": {"moving_jaw": {"faces": len(new_moving.faces), "watertight": bool(new_moving.is_watertight), "volume_cm3": round(new_moving.volume / 1000, 2)},
                        "wrist_roll_follower": {"faces": len(new_fixed.faces), "watertight": bool(new_fixed.is_watertight), "volume_cm3": round(new_fixed.volume / 1000, 2)}}}
    return new_moving, new_fixed, half_m, half_f, pv, report


def _light(m, faces=6000):
    """A simplified copy for the collision check (a quarter of a second each instead of seconds)."""
    try:
        s = m.simplify_quadric_decimation(face_count=faces) if len(m.faces) > faces else m
        return s if s.is_watertight else m
    except Exception:
        return m


def collisions(new_moving, new_fixed, half_m, half_f, q_open=0.45, n=6):
    """Overlap between the parts and the scissors over the gripper's working range, mm^3 (0 is clear)."""
    new_moving, new_fixed, half_m, half_f = (_light(x) for x in (new_moving, new_fixed, half_m, half_f))
    Tf = fixed_to_gripper(); fixed_g = new_fixed.copy().apply_transform(Tf)
    worst = {"jaws": 0.0, "moving_blade_vs_fixed": 0.0, "fixed_blade_vs_moving": 0.0}
    for q in np.linspace(0, q_open, n):
        Tm = moving_to_gripper(q)
        mov = new_moving.copy().apply_transform(Tm)
        hm = half_m.copy().apply_transform(Tm @ np.linalg.inv(moving_to_gripper(0.0)))
        for key, a, b in (("jaws", mov, fixed_g), ("moving_blade_vs_fixed", hm, fixed_g), ("fixed_blade_vs_moving", half_f, mov)):
            try:
                v = trimesh.boolean.intersection([a, b], engine="manifold").volume
            except Exception:
                v = float("nan")
            worst[key] = max(worst[key], round(float(v), 1))
    return worst


def best_design(scan_dir, log=print):
    """Every arrangement (loops forward or back, scissors either way up, either side of the
    gripper), checked for collisions over the working range; the clear one with the shortest arms."""
    best = None
    # The hinge side first (where the stand-in scissors came out clear), stopping at the first clear one.
    order = [(1.0, False, True), (1.0, False, False), (1.0, True, True), (1.0, True, False),
             (-1.0, False, True), (-1.0, False, False), (-1.0, True, True), (-1.0, True, False)]
    for side, forward, flip in order:
            if best is not None and best[0][0] is False:
                break
            if True:
                try:
                    d = design(scan_dir, side=side, loops_forward=forward, flip=flip)
                except Exception as e:
                    log(f"side {side:+.0f} forward {forward} flip {flip}: {type(e).__name__}: {e}"); continue
                col = collisions(*d[:4])
                arms = d[5]["arm_mm"]["moving"] + d[5]["arm_mm"]["fixed"]
                bad = sum(v for v in col.values() if v == v) + (1e6 if any(v != v for v in col.values()) else 0)
                log(f"side {side:+.0f} forward {forward} flip {flip}: collisions {col}, arms {arms:.0f} mm")
                key = (bad > 1.0, bad, arms)
                if best is None or key < best[0]:
                    best = (key, d, col)
    return best[1], best[2]


def write(scan_dir, out_dir=None, log=print):
    out_dir = out_dir or scan_dir
    (new_moving, new_fixed, half_m, half_f, pv, rep), col = best_design(scan_dir, log)
    new_moving.export(os.path.join(out_dir, "custom_moving_jaw.stl")); new_fixed.export(os.path.join(out_dir, "custom_wrist_roll_follower.stl"))
    trimesh.Scene([new_moving, new_fixed.copy().apply_translation((90, 0, 0))]).export(os.path.join(out_dir, "custom_jaws.3mf"))
    half_m.export(os.path.join(out_dir, "scissors_half_moving.stl")); half_f.export(os.path.join(out_dir, "scissors_half_fixed.stl"))
    # The preview: both new parts on the gripper, and the scissors in them, gripper closed.
    trimesh.util.concatenate([new_moving.copy().apply_transform(moving_to_gripper(0.0)), new_fixed.copy().apply_transform(fixed_to_gripper())]).export(
        os.path.join(out_dir, "custom_jaws_preview.stl"))
    trimesh.util.concatenate([half_m, half_f]).export(os.path.join(out_dir, "custom_jaws_scissors.stl"))
    new_moving.copy().apply_transform(moving_to_gripper(0.0)).export(os.path.join(out_dir, "custom_jaws_moving_part.stl"))
    new_fixed.copy().apply_transform(fixed_to_gripper()).export(os.path.join(out_dir, "custom_jaws_fixed_part.stl"))
    half_m.export(os.path.join(out_dir, "custom_jaws_moving_blade.stl")); half_f.export(os.path.join(out_dir, "custom_jaws_fixed_blade.stl"))
    rep["pivot_mm"] = pv.round(2).tolist()
    rep["collisions_mm3"] = col
    json.dump(rep, open(os.path.join(out_dir, "custom_jaws.json"), "w"), indent=1)
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("scan_dir"); a = ap.parse_args()
    print(json.dumps(write(a.scan_dir), indent=1))


def simulate(out_dir, video=None, q_open=0.45, seconds=4.0, fps=30):
    """MuJoCo: the two new parts on the SO-101's gripper hinge, each half of the scissors held rigidly
    in its clip, the gripper's position servo opening and closing. The blades' opening is read
    from the halves' own geometry, so it shows whether the scissors really open with the jaw."""
    import mujoco, subprocess, tempfile
    from PIL import Image
    Tm0 = moving_to_gripper(0.0)
    hm = trimesh.load(os.path.join(out_dir, "scissors_half_moving.stl"))
    # Into the jaw body's frame: part coordinates, then the geom's 18.9 mm offset.
    hm_body = hm.copy().apply_transform(np.linalg.inv(Tm0)); hm_body.apply_translation(MOVING_POS)
    tmp = tempfile.mkdtemp(prefix="customjaws-")
    hm_body.export(os.path.join(tmp, "hm.stl"))
    xml = f"""<mujoco model="so101 custom scissors jaws"><compiler angle="radian" autolimits="true"/>
<option timestep="0.002"/><visual><global offwidth="1280" offheight="960"/></visual>
<default><geom contype="0" conaffinity="0"/></default>
<asset>
  <mesh name="fixed" file="{os.path.abspath(os.path.join(out_dir, 'custom_wrist_roll_follower.stl'))}" scale="0.001 0.001 0.001"/>
  <mesh name="moving" file="{os.path.abspath(os.path.join(out_dir, 'custom_moving_jaw.stl'))}" scale="0.001 0.001 0.001"/>
  <mesh name="hf" file="{os.path.abspath(os.path.join(out_dir, 'scissors_half_fixed.stl'))}" scale="0.001 0.001 0.001"/>
  <mesh name="hm" file="{os.path.join(tmp, 'hm.stl')}" scale="0.001 0.001 0.001"/>
  <material name="jaw" rgba="1 0.82 0.12 1"/><material name="blue" rgba="0.2 0.38 0.9 1"/><material name="steel" rgba="0.75 0.77 0.82 1" specular="0.6"/>
  <texture name="grid" type="2d" builtin="checker" rgb1=".16 .17 .2" rgb2=".12 .13 .15" width="300" height="300"/><material name="floor" texture="grid" texrepeat="12 12"/>
</asset>
<worldbody>
  <light pos="0.1 0.4 0.3" dir="-0.2 -1 -0.6"/><light pos="-0.2 0.3 0.1" dir="0.4 -1 0" diffuse="0.4 0.4 0.4"/>
  <geom type="plane" size="0.5 0.5 0.01" pos="0 -0.12 0" zaxis="0 1 0" material="floor"/>
  <body name="gripper">
    <geom type="mesh" mesh="fixed" pos="{FIXED_POS[0] / 1000} {FIXED_POS[1] / 1000} {FIXED_POS[2] / 1000}" quat="0 1 0 0" material="jaw"/>
    <geom type="mesh" mesh="hf" material="blue"/>
    <body name="jaw" pos="{H[0] / 1000} {H[1] / 1000} {H[2] / 1000}" quat="{' '.join(map(str, JAW_Q))}">
      <joint name="gripper" axis="0 0 1" type="hinge" range="-0.17453 1.74533" damping="0.6" armature="0.028"/>
      <geom type="mesh" mesh="moving" pos="0 0 {MOVING_POS[2] / 1000}" material="jaw" mass="0.03"/>
      <geom type="mesh" mesh="hm" material="steel" mass="0.02"/>
    </body>
  </body>
  <camera name="side" pos="0.03 0.30 -0.04" xyaxes="-1 0 0 0 0 1" fovy="48"/>
  <camera name="three_quarter" pos="0.22 0.22 0.06" xyaxes="-0.7071 0.7071 0 -0.25 -0.25 0.935" fovy="45"/>
</worldbody>
<actuator><position name="gripper" joint="gripper" kp="998.22" forcerange="-3.35 3.35" ctrlrange="-0.17453 1.74533"/></actuator>
</mujoco>"""
    open(os.path.join(out_dir, "custom_jaws_sim.xml"), "w").write(xml)
    m = mujoco.MjModel.from_xml_string(xml); d = mujoco.MjData(m)
    r = mujoco.Renderer(m, 960, 1280) if video else None
    frames, opened = [], []
    hf = trimesh.load(os.path.join(out_dir, "scissors_half_fixed.stl"))
    # The blades' opening: each half's blade (the part more than 25 mm past the pivot towards the
    # tips) as a direction in the scissors' plane. A whole half's long axis is no measure: the
    # loops sit either side of the axis even when the scissors are shut, which read as 12 degrees.
    allv = np.vstack([hm.vertices, hf.vertices]); pv0 = np.array([H[0], 0.0, H[2]])
    u = np.linalg.svd(allv - allv.mean(0), full_matrices=False)[2][0]; u[1] = 0; u /= np.linalg.norm(u)
    if ((allv - pv0) @ u).max() < -((allv - pv0) @ u).min():
        u = -u
    blade_m = (hm.vertices - pv0) @ u > 25.0             # the same points of each blade in every frame
    def ax(mesh, keep=None):
        b = mesh.vertices[(mesh.vertices - pv0) @ u > 25.0 if keep is None else keep]
        b = b - b.mean(0); b[:, 1] = 0
        a = np.linalg.svd(b, full_matrices=False)[2][0]
        return a * np.sign(a @ u)
    a_f = ax(hf)
    for k in range(int(seconds / m.opt.timestep)):
        tt = k * m.opt.timestep
        d.ctrl[0] = q_open * (0.5 - 0.5 * math.cos(2 * math.pi * tt / seconds))
        mujoco.mj_step(m, d)
        if k % int(1 / (fps * m.opt.timestep)) == 0:
            q = float(d.qpos[0])
            hm_now = hm.copy().apply_transform(moving_to_gripper(q) @ np.linalg.inv(Tm0))
            opened.append((q, math.degrees(math.acos(min(1.0, abs(float(ax(hm_now, blade_m) @ a_f)))))))
            if r:
                for cam in ("side", "three_quarter"):
                    r.update_scene(d, camera=cam); frames.append((cam, r.render().copy()))
    closed = opened[0][1]
    rep = {"gripper_max_deg": round(math.degrees(max(q for q, _ in opened)), 1),
           "blades_max_deg": round(max(a for _, a in opened) - closed, 1),
           "blades_closed_deg": round(closed, 1)}
    if video:
        for cam in ("side", "three_quarter"):
            fdir = tempfile.mkdtemp(prefix=f"cj-{cam}-")
            for i, (c, f) in enumerate([x for x in frames if x[0] == cam]):
                Image.fromarray(f).save(os.path.join(fdir, f"f{i:04d}.png"))
            outp = video.replace(".mp4", f"_{cam}.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(fdir, "f%04d.png"),
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", outp], check=True)
            rep[f"video_{cam}"] = outp
    return rep
