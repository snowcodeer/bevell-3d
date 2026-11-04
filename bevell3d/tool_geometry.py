"""A flat hinged tool (scissors, pliers, snips) measured from the photo taken from above.

Deterministic: no model is asked anything. The most top-down photo is flattened onto the sheet
through its camera (the markers measured it), at 0.1 mm a pixel, and read there:

- the pivot is the screw or rivet every such tool turns on: the clearest circle 2 to 8 mm in
  radius inside the tool's outline, close to its long axis, on the blade side of the handles;
- the tool's model is its outline from above (finger loops and blade tips included) extruded to
  its measured thickness. A visual hull carves a thin, partly clear tool badly: on a real pair
  of scissors it lost 35 mm of blade (seen edge-on from low down) and came out 12 mm thick.
"""
import glob, os, pickle
import numpy as np
import cv2
import trimesh
from shapely.geometry import Point, Polygon, LineString

RES = 0.1          # mm per pixel of the flattened photo


def most_overhead(views):
    return max(range(len(views)), key=lambda i: -(cv2.Rodrigues(views[i]["rv"])[0].T @ np.array([0, 0, 1.0]))[2])


def photo_of(scan_dir, name, size=None):
    """The working copy of a photo (the size its camera was measured at): a scan keeps them in
    photos/, beside the full-resolution originals in photos/full/."""
    for pattern in (f"photos/{name}.jpg", f"prepared/{name}.jpg", f"photos/{name}.*", f"prepared/{name}.*"):
        for hit in sorted(glob.glob(os.path.join(scan_dir, pattern))):
            if size is None:
                return hit
            im = cv2.imread(hit)
            if im is not None and (im.shape[1], im.shape[0]) == tuple(size):
                return hit
    return None


def flatten(img, view, bounds, z, res=RES):
    """The photo resampled onto the plane z mm above the sheet over `bounds` (x0, y0, x1, y1):
    returns the image and a function from sheet mm to its pixels."""
    x0, y0, x1, y1 = bounds
    W, H = int((x1 - x0) / res), int((y1 - y0) / res)
    xs, ys = np.meshgrid(x0 + (np.arange(W) + 0.5) * res, y1 - (np.arange(H) + 0.5) * res)
    uv, _ = cv2.projectPoints(np.c_[xs.ravel(), ys.ravel(), np.full(xs.size, z)], view["rv"], view["tv"], view["K"], None)
    uv = uv.reshape(H, W, 2).astype(np.float32)
    flat = cv2.remap(img, uv[..., 0], uv[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    to_px = lambda p: ((p[0] - x0) / res, (y1 - p[1]) / res)
    to_mm = lambda q: (x0 + q[0] * res, y1 - q[1] * res)
    return flat, to_px, to_mm


def find_pivot(scan_dir, outline, info, thickness):
    """The pivot screw or rivet, sheet mm, and how it was found; None if no circle qualifies."""
    vp = pickle.load(open(os.path.join(scan_dir, "views.pkl"), "rb"))
    k = most_overhead(vp["views"]); v = vp["views"][k]
    path = photo_of(scan_dir, v["name"], vp.get("size"))
    if path is None:
        return None, "no photo from above"
    img = cv2.imread(path)
    x0, y0, x1, y1 = outline.bounds
    flat, to_px, to_mm = flatten(img, v, (x0 - 5, y0 - 5, x1 + 5, y1 + 5), thickness)
    gray = cv2.createCLAHE(2.0, (8, 8)).apply(cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY))
    gray = cv2.GaussianBlur(gray, (0, 0), 1.5)
    rmin, rmax = int(2.0 / RES), int(8.0 / RES)
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=4.0 / RES, param1=90, param2=18, minRadius=rmin, maxRadius=rmax)
    if circles is None:
        return None, "no circle in the photo from above"
    ax = np.array(info["long_axis"]); q = np.array(info["grasp_line_mm"])
    mid = np.mean([np.array(h["centre_mm"]) for h in info["handles"]], axis=0)
    toward = -np.sign((mid - np.array(outline.centroid.coords[0])) @ ax) * ax      # from the loops to the blades
    width = outline.minimum_rotated_rectangle
    e = np.array(width.exterior.coords)[:4]; across = min(np.linalg.norm(e[1] - e[0]), np.linalg.norm(e[2] - e[1]))
    inner = outline.buffer(-1.0)
    best = None
    for rank, (cx, cy, r) in enumerate(circles[0]):
        c = np.array(to_mm((cx, cy))); rr = r * RES
        along = (c - q) @ toward                          # how far towards the blades from the grasp line
        off = abs((c - q) @ np.array([-toward[1], toward[0]]))
        if not inner.contains(Point(c)) or along < 8.0 or off > 0.18 * across:
            continue
        # The ring's contrast: a screw head's edge against the blade round it.
        ring = np.zeros(gray.shape, np.uint8); cv2.circle(ring, (int(cx), int(cy)), int(r), 255, max(2, int(0.6 / RES)))
        inside = np.zeros(gray.shape, np.uint8); cv2.circle(inside, (int(cx), int(cy)), max(1, int(r * 0.6)), 255, -1)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0); gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
        edge = float(np.hypot(gx, gy)[ring > 0].mean())
        score = edge / (1 + rank * 0.15) - 0.5 * off
        if best is None or score > best[0]:
            best = (score, c, rr, along, off)
    if best is None:
        return None, "no circle near the tool's axis on the blade side"
    _, c, rr, along, off = best
    return c, {"how": "screw circle in the photo from above", "photo": v["name"], "radius_mm": round(float(rr), 1),
               "from_grasp_line_mm": round(float(along), 1), "off_axis_mm": round(float(off), 1)}


def flat_model(outline, thickness):
    """The tool as its outline from above, holes included, extruded to its thickness (mm, sheet frame)."""
    m = trimesh.creation.extrude_polygon(outline.buffer(0), thickness)
    return m


def tool_thickness(info, lo=3.0, hi=12.0):
    """The handles' measured thickness (the scan's, at the grasp line), within reason."""
    t = float(np.median([h["thickness_mm"] for h in info["handles"]]))
    return float(np.clip(t, lo, hi))


def shown_model(outline, info, pivot, toward, sam=None, reach=400.0):
    """The tool as the preview and the simulation show it, sheet frame: the handles from the
    outline the photos measured, each loop at its own measured thickness and height, and in
    front of the pivot SAM 3D's blades when there is a SAM 3D model (it keeps them thin), else
    the outline there too. SAM 3D's loops are its guess: on a real pair of scissors its finger
    holes came out 60% larger than the photos' and one 4.9 mm off, so a clip fitted to the real
    loop looked as if it cut through the shown one."""
    from shapely.geometry import box as sbox
    from shapely import affinity
    p = np.asarray(pivot, float); a = np.asarray(toward, float) / np.linalg.norm(toward)
    ang = np.degrees(np.arctan2(a[1], a[0]))
    def half(x0, x1, y0, y1):                        # a box in the axis frame, placed at the pivot
        g = sbox(x0, y0, x1, y1)
        return affinity.translate(affinity.rotate(g, ang, origin=(0, 0)), p[0], p[1])
    t_all = tool_thickness(info)
    parts = []
    for side in (1, -1):
        region = outline.intersection(half(-reach, 0, 0, side * reach) if side > 0 else half(-reach, 0, -reach, 0))
        if region.is_empty:
            continue
        cs = [h for h in info["handles"] if np.sign(((np.array(h["centre_mm"]) - p) @ np.array([-a[1], a[0]])) or 1) == side]
        h = cs[0] if cs else None
        z0 = float(h["z_mm"]) if h else 0.0
        th = float(h["thickness_mm"]) if h else t_all
        for g in getattr(region, "geoms", [region]):
            if g.area > 1.0:
                m = trimesh.creation.extrude_polygon(g.buffer(0), th); m.apply_translation((0, 0, z0)); parts.append(m)
    if sam is not None:
        # SAM 3D's own screw (the highest bump within 15 mm of the found pivot) moved onto the
        # pivot, then its blades stretched along the axis to the outline's tip: on the real pair
        # its screw sat 8.1 mm along the axis from the screw in the photo, so the scissors shown
        # turned about a point that was not their screw.
        v = sam.vertices; near = np.linalg.norm(v[:, :2] - p, axis=1) < 15.0
        if near.sum() > 20:
            zn = v[near, 2]; top = v[near][zn > np.percentile(zn, 97)]
            off = p - top[:, :2].mean(0)
            if np.linalg.norm(off) < 15.0:
                sam = sam.copy(); sam.apply_translation(np.r_[off, 0.0])
        blades = sam.slice_plane(np.r_[p, 0.0], np.r_[a, 0.0], cap=False)
        if blades is not None and len(blades.faces):
            l_out = float(max((np.array(c) - p) @ a for c in outline.exterior.coords))
            l_sam = float(((blades.vertices[:, :2] - p) @ a).max())
            k = float(np.clip(l_out / max(l_sam, 1e-6), 0.85, 1.15))
            A = np.r_[a, 0.0]; M = np.eye(4); M[:3, :3] += (k - 1) * np.outer(A, A)
            M[:3, 3] = -(M[:3, :3] @ np.r_[p, 0.0]) + np.r_[p, 0.0]
            blades.apply_transform(M)
    else:
        blades = flat_model(outline.intersection(half(0, reach, -reach, reach)), t_all)
    if blades is not None and len(blades.faces):
        parts.append(blades)
    return trimesh.util.concatenate(parts)
