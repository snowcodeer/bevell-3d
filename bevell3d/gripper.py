"""Gripper pads cut to a scanned object: print two, stick them on the jaws, and the gripper holds
that object by its own shape.

The grasp squeezes across the object's narrow side at a chosen height. Each pad is a block with
a flat back (it sticks to the jaw's inner face with double-sided foam tape) and a shallow cradle
on its front: the object's outer surface, seen from that jaw, offset by a clearance. The cradle
reaches at most `wrap` past the object's widest point, so a hinged jaw like the SO-101's can
still swing clear.

Also writes grasp.json: where on the sheet to grasp, along which axis, and how wide to open,
in the sheet's world frame, so a robot that knows where the sheet is can pick the object.
"""
from dataclasses import dataclass, asdict
import json, os
import numpy as np, trimesh
from scipy import ndimage
from skimage import measure


@dataclass
class PadParams:
    width: float = 20.0         # along the jaw, across the squeeze (the SO-101 jaw is 22.3 mm wide)
    height: float = 30.0        # vertical
    thickness: float = 3.0      # behind the deepest point of the cradle
    wrap: float = 5.0           # how far the cradle reaches past the object's widest point
    clearance: float = 0.3
    grasp_height: float = 0.5   # share of the object's height
    pitch: float = 0.25


def grasp_frame(mesh, p=PadParams()):
    """Squeeze across the footprint's narrow axis, through its centre, at the grasp height."""
    xy = mesh.vertices[:, :2]
    c = xy.mean(0)
    w, V = np.linalg.eigh(np.cov((xy - c).T))
    d, u = V[:, 0], V[:, 1]                       # narrow axis (squeeze), long axis
    z0, z1 = mesh.bounds[0][2], mesh.bounds[1][2]
    zg = z0 + p.grasp_height * (z1 - z0)
    zg = min(max(zg, z0 + p.height / 2 + 1.0), z1 - 1.0) if (z1 - z0) > p.height + 2 else (z0 + z1) / 2
    return np.r_[c, zg], np.r_[d, 0.0], np.r_[u, 0.0]


def _pad(mesh, centre, dvec, uvec, sign, p):
    """One pad, in its own frame (d' outwards from the centre plane, u along the jaw, v up)."""
    pts = mesh.sample(max(60000, int(mesh.area / (p.pitch * p.pitch) * 2)))
    rel = pts - centre
    dd, uu, vv = sign * rel @ dvec, rel @ uvec, rel[:, 2]
    nu, nv = int(np.ceil(p.width / p.pitch)) + 1, int(np.ceil(p.height / p.pitch)) + 1
    iu = np.round((uu + p.width / 2) / p.pitch).astype(int); iv = np.round((vv + p.height / 2) / p.pitch).astype(int)
    keep = (iu >= 0) & (iu < nu) & (iv >= 0) & (iv < nv)
    s = np.full((nu, nv), -np.inf)
    np.maximum.at(s, (iu[keep], iv[keep]), dd[keep])
    hit = np.isfinite(s)
    if not hit.any():
        raise ValueError("the object does not reach the pad: move the grasp height")
    s = np.where(hit, s, -np.inf)
    s = ndimage.grey_dilation(np.where(hit, s, -1e9), size=3)          # close sampling gaps by a cell
    widest = s[s > -1e8].max()
    inner = np.maximum(s + p.clearance, widest - p.wrap)                 # the cradle, no deeper than `wrap`
    inner = np.maximum(inner, 0.5)                                       # never past the centre plane
    back = widest + p.clearance + p.thickness
    ds = np.arange(inner.min() - p.pitch, back + p.pitch, p.pitch)
    vox = (ds[:, None, None] >= inner[None]) & (ds[:, None, None] <= back)
    vol = ndimage.gaussian_filter(np.pad(vox.astype(np.float32), 1), 0.6)
    verts, faces, _, _ = measure.marching_cubes(vol, 0.5, spacing=(p.pitch, p.pitch, p.pitch))
    verts -= p.pitch
    local = np.c_[verts[:, 0] + ds[0], verts[:, 1] - p.width / 2, verts[:, 2] - p.height / 2]   # (d', u, v)
    pad = trimesh.Trimesh(local, faces)
    if pad.volume < 0:
        pad.invert()
    trimesh.smoothing.filter_taubin(pad, lamb=0.5, nu=-0.53, iterations=8)
    # Share of the pad's face where the cradle follows the object (rather than its floor).
    touching = float(np.mean((s > -1e8) & ((s + p.clearance) >= inner - 1e-9)))
    return pad, {"widest_mm": float(widest), "back_mm": float(back), "contact_share": round(touching, 3),
                 "deepest_cradle_mm": round(float(back - inner.min() - p.thickness), 1)}


def make_pads(mesh, p=PadParams()):
    centre, dvec, uvec = grasp_frame(mesh, p)
    pads, info = {}, {}
    for name, sign in (("fixed_jaw", -1.0), ("moving_jaw", 1.0)):
        local, inf = _pad(mesh, centre, dvec, uvec, sign, p)
        # World pose, for previews and checks: d' along sign * d, u along u, v up.
        R = np.c_[sign * dvec, uvec, [0, 0, 1.0]]
        world = trimesh.Trimesh(local.vertices @ R.T + centre, local.faces, process=False)
        if world.volume < 0:                       # the mirrored pad comes out inside out
            world.invert()
        # Print pose: flat back on the bed, cradle facing up.
        printed = trimesh.Trimesh(np.c_[local.vertices[:, 1], local.vertices[:, 2], inf["back_mm"] - local.vertices[:, 0]],
                                  local.faces, process=False)
        printed.apply_translation(-printed.bounds[0])
        if printed.volume < 0:
            printed.invert()
        pads[name] = {"world": world, "print": printed}
        info[name] = inf
    widest = max(info[k]["widest_mm"] for k in info)
    grasp = {
        "centre_mm": [round(float(v), 2) for v in centre], "squeeze_axis": [round(float(v), 4) for v in dvec],
        "jaw_axis": [round(float(v), 4) for v in uvec],
        "open_to_mm": round(2 * (info["fixed_jaw"]["back_mm"] + info["moving_jaw"]["back_mm"]) / 2 + 10, 1),
        "closed_on_object_mm": round(info["fixed_jaw"]["back_mm"] + info["moving_jaw"]["back_mm"], 1),
        "frame": "capture sheet: mm, origin at the printed top-left, X along the long edge, Y up the sheet, Z up",
        "pads": info, "params": asdict(p),
    }
    return pads, grasp


def write_pads(out_dir, mesh, p=PadParams()):
    os.makedirs(out_dir, exist_ok=True)
    pads, grasp = make_pads(mesh, p)
    scene = []
    for name, pr in pads.items():
        pr["print"].export(os.path.join(out_dir, f"pad_{name}.stl"))
        scene.append(pr["print"].copy())
    # Both pads side by side on one plate.
    scene[1].apply_translation((scene[0].extents[0] + 8, 0, 0))
    trimesh.util.concatenate(scene).export(os.path.join(out_dir, "pads.3mf"))
    json.dump(grasp, open(os.path.join(out_dir, "grasp.json"), "w"), indent=1)
    return pads, grasp
