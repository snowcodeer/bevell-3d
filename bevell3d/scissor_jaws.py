"""New SO-101 jaws whose fingertips go through a pair of scissors' finger loops.

    python -m bevell3d.scissor_jaws <scan dir> [--video sim.mp4]

The scissors lie in the jaws' own plane, superimposed on the gripper, blades pointing out past
the fingertips. Each jaw is the SO-101's own (The Robot Studio's), cut off just above its loop,
with a plate behind the loop, a plug through the loop's hole (the hole's own outline from the
photos from above) and a snap lip on the far face that the ring presses over.

The scissors turn about their pivot, ahead of the fingertips; the moving jaw turns about the
gripper hinge, behind them. So the fixed jaw's plug fills its hole, and the moving jaw's plug is
round and as wide as its hole is narrow: it cannot rattle across the loop but slides along it, as
a finger does in a loop. The scissors are placed with the hinge, the moving loop and the pivot in
one line, where the plug and the loop start out moving together and the slide is smallest; the
simulation (MuJoCo, the SO-101's own jaw meshes and hinge) checks it stays inside the hole.

Frames: so101_new_calib.xml's gripper frame, mm (fingertips about 100 mm down, the jaws close
along x, the moving jaw turns about the y axis through H).
"""
import argparse, json, math, os, pickle, subprocess, tempfile
import numpy as np
import trimesh
from shapely.geometry import Point, Polygon, MultiPoint, box as sbox
from shapely import affinity
from .tool_fingers import handles, mesh_outline, top_outline, FingerParams
from .scissors_sim import pivot_of
from .custom_jaws import fixed_to_gripper, moving_to_gripper, H, ROOT, MOVING_POS, FIXED_POS, JAW_Q

REACH = 75.0          # mm from the hinge to the moving loop's hole: where the stock fingertip is
CLEAR = 0.3           # plug to hole
LIP = 0.6             # the snap lip stands this far past the hole
FLAT = 4.5            # the moving plug: a disc as wide as the hole, flattened to +-FLAT mm along it
PLATE = 2.5           # the plate behind the loop, mm thick


def _xz(poly):
    """A shapely polygon in the gripper's x-z plane -> a mesh prism along y, through `y0, y1`."""
    return poly


def _prism(poly, y0, y1):
    """Extrude a polygon given in (x, z) along +y from y0 to y1, as a watertight mesh."""
    m = trimesh.creation.extrude_polygon(poly.buffer(0).simplify(0.03), y1 - y0)   # (x, z) in its x-y, height along z
    # (x, z, h) -> (x, y0 + h, z): swap the extrusion axis onto y.
    v = m.vertices.copy()
    m.vertices = np.c_[v[:, 0], y0 + v[:, 2], v[:, 1]]
    m.fix_normals()
    return m


def layout(scan_dir, p=FingerParams()):
    """Where everything goes: the scissors' outline, holes and pivot in the gripper's x-z plane."""
    src = next(f for f in ("hull.stl", "model.stl") if os.path.exists(os.path.join(scan_dir, f)))
    mesh = trimesh.load(os.path.join(scan_dir, src))
    outline = None
    if os.path.exists(os.path.join(scan_dir, "views.pkl")):
        vp = pickle.load(open(os.path.join(scan_dir, "views.pkl"), "rb"))
        outline = top_outline(vp["views"], vp["masks"], float(mesh.bounds[1][2]) / 2)
    outline = outline if outline is not None else mesh_outline(mesh)
    info = handles(mesh, p, outline=outline)
    if not all(h["loop"] for h in info["handles"]):
        raise ValueError("These jaws are for scissors: both handles need a finger loop.")
    pivot, toward = pivot_of(outline, info)
    t = float(mesh.bounds[1][2] - mesh.bounds[0][2])
    holes = sorted((Polygon(r) for r in outline.interiors), key=lambda g: -g.area)[:2]
    if len(holes) < 2:
        raise ValueError("Both finger loops' holes must show in the photos from above.")
    # The moving loop is the one on the +x side once placed; place with the moving hole straight
    # below the hinge, REACH mm down, and the pivot beyond it on the same line.
    def place(moving_idx):
        hb = holes[moving_idx]
        cb = np.array(hb.centroid.coords[0])
        d = cb - pivot                                         # pivot -> moving hole, sheet frame
        # Rotate the sheet so d points straight up (towards the hinge, +z), then flip if needed so
        # the other hole lands on the -x side (the fixed jaw).
        ang = math.atan2(d[1], d[0])
        def to_g(xy, flip):
            q = np.asarray(xy) - pivot
            c, s = math.cos(math.pi / 2 - ang), math.sin(math.pi / 2 - ang)
            r = np.array([c * q[0] - s * q[1], s * q[0] + c * q[1]])     # d now along +z
            if flip:
                r[0] = -r[0]
            Bz = H[2] - REACH                                   # the moving hole's centre, gripper z
            pz = Bz - np.linalg.norm(d)                         # the pivot, below it on the same line
            return np.array([H[0] + r[0], pz + r[1]])
        for flip in (False, True):
            ca = to_g(holes[1 - moving_idx].centroid.coords[0], flip)
            if ca[0] < H[0]:
                return to_g, flip
        return None, None
    for mi in (0, 1):
        to_g, flip = place(mi)
        if to_g is not None:
            break
    tf = lambda poly: Polygon([to_g(c, flip) for c in poly.exterior.coords], [[to_g(c, flip) for c in r.coords] for r in poly.interiors])
    return {"mesh": mesh, "outline_g": tf(outline), "hole_fixed": tf(holes[1 - mi]), "hole_moving": tf(holes[mi]),
            "pivot_g": to_g(pivot, flip), "t": t, "to_g": to_g, "flip": flip, "info": info}


def jaw_part(stock_g, hole, round_plug, t, y_mid=0.0):
    """One new jaw in the gripper frame: the stock jaw cut off above its loop, a plate behind the
    loop, a plug through the hole and a snap lip."""
    ring_top = hole.bounds[3] + 7.5                       # above the loop's ring (holes ~ 5 mm ring)
    keep = trimesh.creation.box(bounds=[[-200, -200, ring_top], [200, 200, 200]])
    stub = trimesh.boolean.intersection([stock_g, keep], engine="manifold")
    if round_plug:
        # As wide as the hole across (no rattle), short along it (room to slide), and round at its
        # ends so it can turn the few degrees the loop turns against the jaw.
        mrr = np.array(hole.minimum_rotated_rectangle.exterior.coords)[:4]
        e = [mrr[1] - mrr[0], mrr[2] - mrr[1]]
        major = max(e, key=np.linalg.norm); major = major / np.linalg.norm(major)
        w = float(min(np.linalg.norm(x) for x in e))
        c = hole.centroid
        disc = c.buffer(w / 2 - CLEAR, 64)
        n = np.array([-major[1], major[0]])
        strip = Polygon([np.array(c.coords[0]) + major * sa * FLAT + n * sb * w for sa, sb in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
        plug2d = disc.intersection(strip)
    else:
        plug2d = hole.buffer(-CLEAR, 32)
    near = stub.vertices[stub.vertices[:, 2] < ring_top + 4]
    root = MultiPoint([(x, z) for x, _, z in near]).convex_hull.buffer(0.5) if len(near) > 2 else sbox(-5, ring_top, 5, ring_top + 4)
    plate2d = MultiPoint(list(hole.buffer(2.2, 32).exterior.coords) + list(root.exterior.coords)).convex_hull
    y_back = y_mid - t / 2 - 0.15                          # the plate stops just behind the ring
    plate = _prism(plate2d, y_back - PLATE, y_back)
    plug = _prism(plug2d, y_back - 0.5, y_mid + t / 2 + CLEAR)
    lip = _prism(plug2d.buffer(LIP, 32), y_mid + t / 2 + CLEAR, y_mid + t / 2 + CLEAR + 0.9)
    part = trimesh.boolean.union([stub, plate, plug, lip], engine="manifold")
    return part, {"plug": "round" if round_plug else "hole-shaped", "plug_mm": round(2 * math.sqrt(plug2d.area / math.pi), 2),
                  "hole_mm": [round(v, 1) for v in np.ptp(np.array(hole.exterior.coords), axis=0)], "lip_mm": LIP}


def design(scan_dir):
    L = layout(scan_dir)
    fixed = trimesh.load(os.path.join(ROOT, "assets", "wrist_roll_follower_so101_v1.stl")); fixed.apply_scale(1000)
    moving = trimesh.load(os.path.join(ROOT, "assets", "moving_jaw_so101_v1.stl")); moving.apply_scale(1000)
    Tf, Tm0 = fixed_to_gripper(), moving_to_gripper(0.0)
    fg = fixed.copy().apply_transform(Tf); mg = moving.copy().apply_transform(Tm0)
    new_f, df = jaw_part(fg, L["hole_fixed"], False, L["t"])
    new_m, dm = jaw_part(mg, L["hole_moving"], True, L["t"])
    # The scissors in the gripper frame, for the simulation and the preview: the scan's outline
    # extruded through its thickness, cut into the two halves along the line through the pivot.
    t = L["t"]
    sc = _prism(L["outline_g"], -t / 2, t / 2)
    pv = np.array([L["pivot_g"][0], 0.0, L["pivot_g"][1]])
    ca = np.array(L["hole_fixed"].centroid.coords[0]); cb = np.array(L["hole_moving"].centroid.coords[0])
    nrm = np.array([cb[0] - ca[0], 0, cb[1] - ca[1]]); nrm /= np.linalg.norm(nrm)
    half_m = sc.slice_plane(pv, nrm, cap=True); half_f = sc.slice_plane(pv, -nrm, cap=True)
    return {"moving": new_m, "fixed": new_f, "half_m": half_m, "half_f": half_f, "pivot": pv, "layout": L,
            "report": {"fixed_jaw": df, "moving_jaw": dm, "pivot_mm": pv.round(1).tolist(), "reach_mm": REACH,
                       "parts_watertight": [bool(new_m.is_watertight), bool(new_f.is_watertight)]}}


def simulate(D, video=None, q_open=0.3, seconds=4.0, fps=30, work=None):
    """MuJoCo: half F rigid on the fixed jaw, half M on the scissors' pivot, and the moving jaw's
    round plug as a pin in a slot along the moving hole's long axis. The gripper's servo opens and
    closes; report the blades' opening, the plug's slide and whether it stays inside the hole."""
    import mujoco
    from PIL import Image
    work = work or tempfile.mkdtemp(prefix="scissorjaws-")
    Tm0 = moving_to_gripper(0.0)
    L = D["layout"]; pv = D["pivot"]
    hb = L["hole_moving"]
    mrr = np.array(hb.minimum_rotated_rectangle.exterior.coords)[:4]
    edges = [mrr[1] - mrr[0], mrr[2] - mrr[1]]
    major = max(edges, key=np.linalg.norm); length = float(np.linalg.norm(major)); major = major / length
    width = float(min(np.linalg.norm(e) for e in edges))
    cb = np.array(hb.centroid.coords[0])
    free = length / 2 - FLAT - CLEAR                           # how far the plug can slide each way
    # Meshes: parts in their own bodies' frames (m).
    new_m_body = D["moving"].copy().apply_transform(np.linalg.inv(Tm0)); new_m_body.apply_translation(MOVING_POS)
    new_f_g = D["fixed"]
    hm_rel = D["half_m"].copy(); hm_rel.apply_translation(-pv)
    files = {}
    for name, m in (("moving", new_m_body), ("fixed", new_f_g), ("hf", D["half_f"]), ("hm", hm_rel)):
        files[name] = os.path.join(work, f"{name}.stl"); m.export(files[name])
    gq = moving_to_gripper(0.0)
    plug_body = (np.linalg.inv(Tm0) @ np.r_[cb[0], 0.0, cb[1], 1])[:3] + MOVING_POS   # plug centre, jaw body frame (mm)
    slot_anchor = np.array([cb[0], 0.0, cb[1]]) - pv                                     # in half M's frame (mm)
    axis = np.array([major[0], 0.0, major[1]])
    xml = f"""<mujoco model="so101 scissor jaws"><compiler angle="radian" autolimits="true"/>
<option timestep="0.002"/><visual><global offwidth="1280" offheight="960"/></visual>
<default><geom contype="0" conaffinity="0"/></default>
<asset>
  <mesh name="fixed" file="{files['fixed']}" scale="0.001 0.001 0.001"/><mesh name="moving" file="{files['moving']}" scale="0.001 0.001 0.001"/>
  <mesh name="hf" file="{files['hf']}" scale="0.001 0.001 0.001"/><mesh name="hm" file="{files['hm']}" scale="0.001 0.001 0.001"/>
  <material name="jaw" rgba="1 0.82 0.12 1"/><material name="blue" rgba="0.2 0.38 0.9 1"/><material name="steel" rgba="0.75 0.77 0.82 1" specular="0.6"/>
  <texture name="grid" type="2d" builtin="checker" rgb1=".16 .17 .2" rgb2=".12 .13 .15" width="300" height="300"/><material name="floor" texture="grid" texrepeat="12 12"/>
</asset>
<worldbody>
  <light pos="0.05 -0.4 0.2" dir="0 1 -0.4"/><light pos="-0.2 -0.3 -0.1" dir="0.4 1 0.2" diffuse="0.4 0.4 0.4"/>
  <geom type="plane" size="0.6 0.6 0.01" pos="0 0.08 0" zaxis="0 -1 0" material="floor"/>
  <body name="gripper">
    <geom type="mesh" mesh="fixed" material="jaw"/>
    <body name="jaw" pos="{H[0] / 1000} {H[1] / 1000} {H[2] / 1000}" quat="{' '.join(map(str, JAW_Q))}">
      <joint name="gripper" axis="0 0 1" type="hinge" range="-0.17453 1.74533" damping="0.6" armature="0.028"/>
      <geom type="mesh" mesh="moving" pos="0 0 0" material="jaw" mass="0.03"/>
    </body>
    <body name="half_f"><geom type="mesh" mesh="hf" material="blue" mass="0.02"/>
      <body name="half_m" pos="{pv[0] / 1000} {pv[1] / 1000} {pv[2] / 1000}">
        <joint name="scissors" type="hinge" axis="0 1 0" range="-1.2 1.2" damping="0.002"/>
        <geom type="mesh" mesh="hm" material="steel" mass="0.02"/>
        <body name="slot" pos="{slot_anchor[0] / 1000} {slot_anchor[1] / 1000} {slot_anchor[2] / 1000}">
          <joint name="slide" type="slide" axis="{axis[0]} {axis[1]} {axis[2]}" range="-0.04 0.04" damping="0.02"/>
          <geom type="sphere" size="0.001" mass="0.001"/>
        </body>
      </body>
    </body>
  </body>
  <camera name="side" pos="0.02 -0.42 -0.12" xyaxes="1 0 0 0 0 1" fovy="50"/>
  <camera name="three_quarter" pos="0.28 -0.3 -0.02" xyaxes="0.7071 0.7071 0 -0.2 0.2 0.96" fovy="48"/>
</worldbody>
<equality><connect body1="slot" body2="jaw" anchor="0 0 0" solref="0.004 1"/></equality>
<actuator><position name="gripper" joint="gripper" kp="998.22" forcerange="-3.35 3.35" ctrlrange="-0.17453 1.74533"/></actuator>
</mujoco>"""
    # The connect anchor is defined at the model's own pose (gripper 0, scissors closed, slide 0),
    # where the slot point and the plug centre coincide by construction.
    m = mujoco.MjModel.from_xml_string(xml); d = mujoco.MjData(m)
    js, jl, jg = (m.joint(n).qposadr[0] for n in ("scissors", "slide", "gripper"))
    r = mujoco.Renderer(m, 960, 1280) if video else None
    rows, frames = [], []
    for k in range(int(seconds / m.opt.timestep)):
        tt = k * m.opt.timestep
        d.ctrl[0] = q_open * (0.5 - 0.5 * math.cos(2 * math.pi * tt / seconds))
        mujoco.mj_step(m, d)
        if k % int(1 / (fps * m.opt.timestep)) == 0:
            gap = float(np.abs(d.efc_pos[:3]).max()) * 1000 if d.nefc >= 3 else 0.0
            rows.append((float(d.qpos[jg]), math.degrees(float(d.qpos[js])), float(d.qpos[jl]) * 1000, gap))
            if r:
                for cam in ("side", "three_quarter"):
                    r.update_scene(d, camera=cam); frames.append((cam, r.render().copy()))
    slide = [x[2] for x in rows]
    rep = {"gripper_max_deg": round(math.degrees(max(x[0] for x in rows)), 1), "blades_max_deg": round(max(abs(x[1]) for x in rows), 1),
           "slide_mm": [round(min(slide), 2), round(max(slide), 2)], "slide_room_mm": round(free, 2),
           "stays_in_hole": bool(max(abs(min(slide)), abs(max(slide))) <= free), "joint_gap_max_mm": round(max(x[3] for x in rows), 3)}
    if video:
        for cam in ("side", "three_quarter"):
            fdir = tempfile.mkdtemp(prefix=f"sj-{cam}-")
            for i, (c, f) in enumerate([x for x in frames if x[0] == cam]):
                Image.fromarray(f).save(os.path.join(fdir, f"f{i:04d}.png"))
            outp = video.replace(".mp4", f"_{cam}.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(fdir, "f%04d.png"),
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", outp], check=True)
            rep[f"video_{cam}"] = outp
    return rep, xml


def write(scan_dir, out_dir=None, video=None):
    out_dir = out_dir or scan_dir
    D = design(scan_dir)
    Tf, Tm0 = fixed_to_gripper(), moving_to_gripper(0.0)
    m_part = D["moving"].copy().apply_transform(np.linalg.inv(Tm0)); f_part = D["fixed"].copy().apply_transform(np.linalg.inv(Tf))
    m_part.export(os.path.join(out_dir, "scissor_moving_jaw.stl")); f_part.export(os.path.join(out_dir, "scissor_wrist_roll_follower.stl"))
    trimesh.Scene([m_part, f_part.copy().apply_translation((90, 0, 0))]).export(os.path.join(out_dir, "scissor_jaws.3mf"))
    trimesh.util.concatenate([D["moving"], D["fixed"]]).export(os.path.join(out_dir, "scissor_jaws_preview.stl"))
    trimesh.util.concatenate([D["half_m"], D["half_f"]]).export(os.path.join(out_dir, "scissor_jaws_scissors.stl"))
    sim, xml = simulate(D, video)
    open(os.path.join(out_dir, "scissor_jaws_sim.xml"), "w").write(xml)
    rep = {**D["report"], "sim": sim}
    json.dump(rep, open(os.path.join(out_dir, "scissor_jaws.json"), "w"), indent=1)
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("scan_dir"); ap.add_argument("--video"); a = ap.parse_args()
    print(json.dumps(write(a.scan_dir, video=a.video), indent=1))
