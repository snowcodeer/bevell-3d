"""The SO-101 working a pair of scanned scissors, in MuJoCo.

    python -m bevell3d.scissors_sim <scan dir> [--video sim.mp4]

The gripper is The Robot Studio's SO-101 (third_party/so101: its jaw meshes and the hinge from
so101_new_calib.xml). The scissors are the scan split down the middle into two halves on a
hinge at their pivot, stood in the jaws' plane with the blades down: half A tied rigidly to the
fixed jaw's saddle, half B's loop joined to the moving jaw's saddle by a ball joint on a short
slide along the jaw (the tie is loose round the loop, so the loop can slide in the groove; the
two arcs, the jaw's about the gripper hinge and the loop's about the scissors pivot, are not
the same). The gripper's own position servo then opens and closes. The report says how far the
blades open for how far the gripper opens, how far the loop slides, and whether the joint held.
"""
import argparse, json, math, os, pickle, subprocess, tempfile
import numpy as np
import trimesh
import mujoco
from .tool_fingers import handles, mesh_outline, top_outline, FingerParams, _intervals

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "third_party", "so101")
JAW_HINGE = ("0.0202 0.0188 -0.0234", np.array([0.707107, 0.707107, 0.0, 0.0]))   # moving jaw body, from the SO-101 model


def pivot_of(outline, info):
    """Where the scissors turn: along the long axis from the loops towards the blades, the first
    place a line across meets one piece instead of two (the shanks have joined), a little further
    on (the pivot disc's middle)."""
    from shapely.geometry import Polygon
    filled = Polygon(outline.exterior)
    ax, perp = np.array(info["long_axis"]), np.array(info["squeeze_axis"])
    q = np.array(info["grasp_line_mm"])
    mid = np.mean([np.array(h["centre_mm"]) for h in info["handles"]], axis=0)
    toward = -np.sign((mid - filled.centroid.coords[0]) @ ax) * ax      # from the loops to the blades
    for s in np.arange(0, 120, 0.5):
        p = q + toward * s
        iv = _intervals(filled, p, perp)
        if len(iv) == 1:
            c = p + perp * (iv[0][0] + iv[0][1]) / 2
            return c + toward * 6.0, toward
    raise ValueError("Could not find where the handles meet.")


def _jaw_inner_x(model, data, z_mm, q):
    """The moving jaw's inner face (smallest x) at height z, gripper frame, mm, at opening q."""
    data.qpos[0] = q; mujoco.mj_forward(model, data)
    gi = 1; mid = model.geom_dataid[gi]; a, n = model.mesh_vertadr[mid], model.mesh_vertnum[mid]
    v = (model.mesh_vert[a:a + n] @ data.geom_xmat[gi].reshape(3, 3).T + data.geom_xpos[gi]) * 1000
    near = v[np.abs(v[:, 2] - z_mm) < 2.5]
    return near[:, 0].min() if len(near) else np.nan


def _gripper_only():
    xml = f"""<mujoco><compiler angle="radian" meshdir="{ROOT}/assets" autolimits="true"/>
<asset><mesh file="wrist_roll_follower_so101_v1.stl"/><mesh file="moving_jaw_so101_v1.stl"/></asset>
<worldbody><body name="gripper"><geom type="mesh" pos="0 -0.000218214 0.000949706" quat="0 1 0 0" mesh="wrist_roll_follower_so101_v1"/>
<body name="jaw" pos="{JAW_HINGE[0]}" quat="{' '.join(map(str, JAW_HINGE[1]))}"><joint name="gripper" axis="0 0 1" type="hinge"/>
<geom type="mesh" pos="0 0 0.0189" mesh="moving_jaw_so101_v1"/></body></body></worldbody></mujoco>"""
    m = mujoco.MjModel.from_xml_string(xml)
    return m, mujoco.MjData(m)


def _quat_mul(a, b):
    w1, x1, y1, z1 = a; w2, x2, y2, z2 = b
    return np.array([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2])


def _fixed_inner_x(model, data, z_mm):
    """The fixed jaw's inner face (largest x of its finger) at height z, gripper frame, mm."""
    mujoco.mj_forward(model, data)
    gi = 0; mid = model.geom_dataid[gi]; a, n = model.mesh_vertadr[mid], model.mesh_vertnum[mid]
    v = (model.mesh_vert[a:a + n] @ data.geom_xmat[gi].reshape(3, 3).T + data.geom_xpos[gi]) * 1000
    near = v[(np.abs(v[:, 2] - z_mm) < 2.5) & (v[:, 0] < 0)]
    return float(near[:, 0].max())


def build(scan_dir, open_by=0.2, p=FingerParams(), work=None, z_loops=-75.0, rail_vis=20.0):
    """The MuJoCo model of the gripper holding these scissors, and what it was built from."""
    work = work or tempfile.mkdtemp(prefix="scissors-sim-")
    src = next(f for f in ("hull.stl", "model.stl") if os.path.exists(os.path.join(scan_dir, f)))
    mesh = trimesh.load(os.path.join(scan_dir, src))
    outline = None
    if os.path.exists(os.path.join(scan_dir, "views.pkl")):
        vp = pickle.load(open(os.path.join(scan_dir, "views.pkl"), "rb"))
        outline = top_outline(vp["views"], vp["masks"], float(mesh.bounds[1][2]) / 2)
    outline = outline if outline is not None else mesh_outline(mesh)
    info = handles(mesh, p, outline=outline)
    pivot, toward = pivot_of(outline, info)
    perp = np.array(info["squeeze_axis"])
    # Scissors frame: u from the pivot to the loops, v across from handle 0 to handle 1, w up.
    u = -toward; v = perp if (np.array(info["handles"][1]["centre_mm"]) - pivot) @ perp > 0 else -perp
    order = [0, 1] if v @ perp > 0 else [1, 0]
    hA, hB = info["handles"][order[0]], info["handles"][order[1]]
    S = lambda xy: np.array([(np.asarray(xy) - pivot) @ u, (np.asarray(xy) - pivot) @ v])
    # Gripper frame (mm): u -> +z (loops above the pivot, blades down), v -> +x (A on the fixed jaw), w -> +y.
    zA = z_loops                                   # high enough that the loop's slide stays on the finger
    cA, cB = S(hA["centre_mm"]), S(hB["centre_mm"])
    outerA = cA[1] - hA["width_mm"] / 2          # loop A's outer edge, towards the fixed jaw
    outerB = cB[1] + hB["width_mm"] / 2
    gm, gd = _gripper_only()
    x_fixed = _fixed_inner_x(gm, gd, zA)           # the fixed jaw's inner face there (SO-101 mesh)
    off = np.array([zA - cA[0], x_fixed + p.back - outerA])           # (dz, dx) placing the scissors
    t = mesh.bounds[1][2] - mesh.bounds[0][2]
    to_g = lambda uu, vv, ww=0.0: np.array([vv + off[1], ww - t / 2 - 0.2, uu + off[0]])
    pivot_g = to_g(0.0, 0.0)
    contactB = to_g(cB[0], outerB)                # where loop B's ring meets the moving saddle
    # Halves: the scan in the scissors frame, cut down the middle (v = 0).
    M = mesh.copy()
    P = M.vertices[:, :2] - pivot
    M.vertices = np.c_[P @ v + off[1], M.vertices[:, 2] - t / 2 - 0.2, P @ u + off[0]]
    halves = {}
    for name, normal in (("a", [-1, 0, 0]), ("b", [1, 0, 0])):
        h = M.slice_plane(plane_origin=[pivot_g[0], 0, 0], plane_normal=normal, cap=True)
        if name == "b":
            h.apply_translation(-pivot_g)        # half B's body sits at the pivot
        path = os.path.join(work, f"half_{name}.stl")
        (h.copy().apply_scale(0.001) if True else h).export(path)
        halves[name] = path
    # The gripper opening at which the moving jaw's face meets loop B's saddle.
    target = contactB[0] + p.back
    lo, hi = 0.0, 1.6
    for _ in range(40):
        mid = (lo + hi) / 2
        x = _jaw_inner_x(gm, gd, contactB[2], mid)
        if np.isnan(x) or x > target:
            hi = mid
        else:
            lo = mid
    q0 = (lo + hi) / 2
    # The rail points at the scissors' pivot. Along that line the loop cannot move (it keeps its
    # distance from the pivot), so the jaw drives it straight along its path and the rail takes up
    # only where the jaw's arc and the loop's part. A rail along the finger came within a few
    # degrees of the loop's path and let the loop run: 62 degrees of blade for 3 of gripper.
    za, zb = contactB[2] + 12, contactB[2] - 18
    fa = np.array([_jaw_inner_x(gm, gd, za, q0), 0.0, za]); fb = np.array([_jaw_inner_x(gm, gd, zb, q0), 0.0, zb])
    finger = (fb - fa) / np.linalg.norm(fb - fa)
    face = (pivot_g - contactB) / np.linalg.norm(pivot_g - contactB)     # from the contact towards the pivot
    rail_tilt = math.degrees(math.acos(abs(float(face @ finger))))
    gd.qpos[0] = q0; mujoco.mj_forward(gm, gd)
    jaw_pos, jaw_mat = gd.xpos[2].copy(), gd.xmat[2].reshape(3, 3).copy()
    slot_local = jaw_mat.T @ (contactB / 1000 - jaw_pos)            # saddle point in the jaw's frame
    zs = jaw_mat.T @ face; ys = jaw_mat.T @ np.array([0, 1.0, 0]); xs = np.cross(ys, zs)
    Rs = np.c_[xs, ys, zs]
    slot_quat = np.zeros(4); mujoco.mju_mat2Quat(slot_quat, Rs.flatten())
    along = np.array([0, 0, 1.0])                                     # the slide, in the slot's own frame
    # The jaw body posed at q0, with ref = q0, so the model is defined where the loop meets its saddle.
    half = q0 / 2
    qj = _quat_mul(JAW_HINGE[1], np.array([math.cos(half), 0, 0, math.sin(half)]))
    sA = np.array([p.back, 12.0, 24.0]) / 2000                        # saddle boxes (half sizes, m)
    cAg = to_g(cA[0], outerA - p.back / 2) / 1000
    xml = f"""<mujoco model="so101 scissors">
<compiler angle="radian" meshdir="{ROOT}/assets" autolimits="true"/>
<option timestep="0.002" gravity="0 0 -9.81"/>
<visual><global offwidth="1280" offheight="960"/><quality shadowsize="4096"/></visual>
<default><geom contype="0" conaffinity="0"/></default>
<asset>
  <mesh file="wrist_roll_follower_so101_v1.stl"/><mesh file="moving_jaw_so101_v1.stl"/>
  <mesh name="half_a" file="{halves['a']}"/><mesh name="half_b" file="{halves['b']}"/>
  <material name="jaw" rgba="1 0.82 0.12 1"/><material name="saddle" rgba="0.95 0.45 0.12 1"/>
  <material name="steel" rgba="0.72 0.75 0.8 1" specular="0.6"/><material name="grip" rgba="0.2 0.38 0.9 1"/>
  <texture name="grid" type="2d" builtin="checker" rgb1=".16 .17 .2" rgb2=".12 .13 .15" width="300" height="300"/>
  <material name="floor" texture="grid" texrepeat="12 12"/>
</asset>
<worldbody>
  <light pos="0.1 -0.4 0.3" dir="-0.2 1 -0.6" diffuse="0.9 0.9 0.9"/><light pos="-0.2 -0.3 0.1" dir="0.4 1 0" diffuse="0.4 0.4 0.4"/>
  <geom type="plane" size="0.5 0.5 0.01" pos="0 0.08 0" zaxis="0 -1 0" material="floor"/>
  <body name="gripper" pos="0 0 0">
    <geom type="mesh" mesh="wrist_roll_follower_so101_v1" pos="0 -0.000218214 0.000949706" quat="0 1 0 0" material="jaw"/>
    <geom type="box" size="{sA[0]} {sA[1]} {sA[2]}" pos="{cAg[0]} {cAg[1]} {cAg[2]}" material="saddle"/>
    <body name="jaw" pos="{JAW_HINGE[0]}" quat="{' '.join(f'{c:.6f}' for c in qj)}">
      <joint name="gripper" axis="0 0 1" type="hinge" ref="{q0:.6f}" range="-0.17453 1.74533" damping="0.6" armature="0.028"/>
      <geom type="mesh" mesh="moving_jaw_so101_v1" pos="0 0 0.0189" material="jaw"/>
      <body name="slot" pos="{slot_local[0]:.6f} {slot_local[1]:.6f} {slot_local[2]:.6f}" quat="{' '.join(f'{c:.6f}' for c in slot_quat)}">
        <joint name="slot" type="slide" axis="0 0 1" range="-0.03 0.03" damping="0.05"/>
        <geom type="sphere" size="0.0025" material="saddle" mass="0.002"/>
      </body>
      <geom type="box" size="{sA[0]} {sA[1]} {(24 + rail_vis) / 2000:.5f}" material="saddle"
            pos="{(slot_local + Rs @ np.array([p.back / 2000, 0, 0]))[0]:.6f} {(slot_local + Rs @ np.array([p.back / 2000, 0, 0]))[1]:.6f} {(slot_local + Rs @ np.array([p.back / 2000, 0, 0]))[2]:.6f}"
            quat="{' '.join(f'{c:.6f}' for c in slot_quat)}"/>
    </body>
    <body name="half_a">
      <geom type="mesh" mesh="half_a" material="grip" mass="0.02"/>
      <body name="half_b" pos="{pivot_g[0] / 1000:.6f} {pivot_g[1] / 1000:.6f} {pivot_g[2] / 1000:.6f}">
        <joint name="scissors" type="hinge" axis="0 1 0" range="-0.9 0.9" damping="0.002"/>
        <geom type="mesh" mesh="half_b" material="steel" mass="0.02"/>
      </body>
    </body>
  </body>
  <camera name="side" pos="0.0 -0.32 -0.06" xyaxes="1 0 0 0 0 1" fovy="45"/>
</worldbody>
<equality><connect body1="half_b" body2="slot" anchor="{(contactB - pivot_g)[0] / 1000:.6f} {(contactB - pivot_g)[1] / 1000:.6f} {(contactB - pivot_g)[2] / 1000:.6f}" solref="0.004 1"/></equality>
<actuator><position name="gripper" joint="gripper" kp="998.22" kv="0" forcerange="-3.35 3.35" ctrlrange="-0.17453 1.74533"/></actuator>
</mujoco>"""
    meta = {"pivot_from_loops_mm": round(float(abs(cA[0])), 1), "q0_rad": round(q0, 4), "moving_handle": int(order[1]),
            "rail_to_finger_deg": round(rail_tilt, 1),
            "contact_B_mm": contactB.round(1).tolist(), "pivot_mm": pivot_g.round(1).tolist(), "open_by_rad": open_by}
    return xml, meta, work


def simulate(xml, meta, video=None, seconds=4.0, fps=30):
    m = mujoco.MjModel.from_xml_string(xml); d = mujoco.MjData(m)
    q0, dq = meta["q0_rad"], meta["open_by_rad"]
    jg, js, jsl = (m.joint(n).qposadr[0] for n in ("gripper", "scissors", "slot"))
    renderer = mujoco.Renderer(m, 960, 1280) if video else None
    frames, rows = [], []
    steps = int(seconds / m.opt.timestep)
    for k in range(steps):
        t = k * m.opt.timestep
        phase = 0.5 - 0.5 * math.cos(2 * math.pi * t / seconds)                # closed -> open -> closed
        d.ctrl[0] = q0 + dq * phase
        mujoco.mj_step(m, d)
        if k % int(1 / (fps * m.opt.timestep)) == 0:
            # How far apart the two ends of the ball joint are: whether the loop stayed in its saddle.
            mujoco.mj_kinematics(m, d)
            gap = 0.0
            if d.nefc:
                gap = float(np.abs(d.efc_pos[:3]).max()) * 1000 if len(d.efc_pos) >= 3 else 0.0
            rows.append({"t": round(t, 3), "gripper_rad": round(float(d.qpos[jg]), 4), "blades_deg": round(math.degrees(float(d.qpos[js])), 2),
                         "slide_mm": round(float(d.qpos[jsl]) * 1000, 2), "joint_gap_mm": round(gap, 3)})
            if renderer:
                renderer.update_scene(d, camera="side"); frames.append(renderer.render().copy())
    blades = [abs(r["blades_deg"]) for r in rows]; slide = [r["slide_mm"] for r in rows]
    report = {**meta, "gripper_open_rad": [q0, round(q0 + dq, 4)], "gripper_open_deg": round(math.degrees(dq), 1),
              "blades_open_deg": round(max(blades), 1), "slide_mm": [round(min(slide), 2), round(max(slide), 2)],
              "joint_gap_max_mm": round(max(r["joint_gap_mm"] for r in rows), 3), "samples": rows[::6]}
    if video and frames:
        tmp = tempfile.mkdtemp(prefix="simframes-")
        from PIL import Image
        for i, f in enumerate(frames):
            Image.fromarray(f).save(os.path.join(tmp, f"f{i:04d}.png"))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(tmp, "f%04d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", video], check=True)
        report["video"] = video
    return report


def tune(scan_dir, blades_deg=22.0, video=None):
    """The smallest gripper opening that opens the blades `blades_deg`, simulated, and the slide
    the moving saddle's rail must allow there (with 3 mm to spare)."""
    best = None
    for open_by in np.arange(0.06, 0.36, 0.02):
        xml, meta, _ = build(scan_dir, float(open_by))
        rep = simulate(xml, meta)
        best = (xml, meta, rep)
        if rep["blades_open_deg"] >= blades_deg:
            break
    xml, meta, rep = best
    rail = round(2 * max(abs(x) for x in rep["slide_mm"]) + 3.0, 1)
    if video:                                  # drawn with the rail at its length
        xml, meta, _ = build(scan_dir, meta["open_by_rad"], rail_vis=rail)
        rep = simulate(xml, meta, video)
    rep["rail_mm"] = rail
    rep["held"] = rep["joint_gap_max_mm"] < 0.5
    return xml, rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scan_dir"); ap.add_argument("--video"); ap.add_argument("--open-by", type=float, default=0.32)
    a = ap.parse_args()
    xml, meta, work = build(a.scan_dir, a.open_by)
    open(os.path.join(a.scan_dir, "scissors_sim.xml"), "w").write(xml)
    rep = simulate(xml, meta, a.video)
    json.dump(rep, open(os.path.join(a.scan_dir, "scissors_sim.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k != "samples"}, indent=1))
