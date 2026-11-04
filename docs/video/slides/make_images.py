"""Images for the video slides, from the dark scissors scan (out/black_scissors) and the clear pair.
    .venv/bin/python docs/video/slides/make_images.py
"""
import json, os, pickle, sys
import numpy as np, cv2, trimesh
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "video", "slides", "img")
SCAN = os.path.join(ROOT, "out", "black_scissors")
BG, CARD, LINE, ACC, PALE, MUTED = "#14161A", "#1B1E24", "#2A2E36", "#395AF6", "#8095F9", "#9AA0AA"
ACC_BGR = (246, 90, 57)
os.makedirs(OUT, exist_ok=True)
vp = pickle.load(open(os.path.join(SCAN, "views.pkl"), "rb"))
views, masks = vp["views"], vp["masks"]
photo = lambda name: cv2.imread(os.path.join(SCAN, "photos", name + ".jpg"))


def contact_sheet():
    names = sorted(f for f in os.listdir(os.path.join(SCAN, "photos")) if f.endswith(".jpg"))
    ims = [cv2.imread(os.path.join(SCAN, "photos", n)) for n in names]
    tw, th = 330, 248
    cols = 5; rows = (len(ims) + cols - 1) // cols; gap = 14
    can = np.full((rows * th + (rows - 1) * gap, cols * tw + (cols - 1) * gap, 3), (0x1A, 0x16, 0x14), np.uint8)
    for i, im in enumerate(ims):
        h, w = im.shape[:2]
        if h > w:                                   # portrait: centre-crop to the tile's landscape shape
            im = cv2.rotate(im, cv2.ROTATE_90_CLOCKWISE) if False else im
        s = max(tw / w, th / h); im = cv2.resize(im, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        y0 = (im.shape[0] - th) // 2; x0 = (im.shape[1] - tw) // 2; im = im[y0:y0 + th, x0:x0 + tw]
        r, c = divmod(i, cols)
        can[r * (th + gap):r * (th + gap) + th, c * (tw + gap):c * (tw + gap) + tw] = im
    cv2.imwrite(os.path.join(OUT, "photos.jpg"), can, [cv2.IMWRITE_JPEG_QUALITY, 92])


def layout():
    return json.load(open(os.path.join(ROOT, "assets", "capture_sheet_layout.json")))


def markers_photo(k=None):
    """One photo with the sheet's squares drawn back through its measured camera."""
    lay = layout()
    if k is None:                                    # a landscape photo from about 45 degrees
        down = lambda v: -(cv2.Rodrigues(v["rv"])[0].T @ np.array([0, 0, 1.0]))[2]
        ok = [i for i, v in enumerate(views) if photo(v["name"]).shape[1] > photo(v["name"]).shape[0]] or list(range(len(views)))
        k = min(ok, key=lambda i: abs(down(views[i]) - 0.72))
    v = views[k]; im = photo(v["name"]).copy()
    ov = im.copy()
    for cid, cs in lay["corners_mm"].items():
        P = np.c_[np.array(cs, float), np.zeros(4)]
        uv, _ = cv2.projectPoints(P, v["rv"], v["tv"], v["K"], None)
        pts = uv.reshape(-1, 2).astype(np.int32)
        cv2.fillPoly(ov, [pts], ACC_BGR)
        cv2.polylines(im, [pts], True, ACC_BGR, 3, cv2.LINE_AA)
    im = cv2.addWeighted(ov, 0.35, im, 0.65, 0)
    for cid, cs in lay["corners_mm"].items():
        P = np.c_[np.array(cs, float), np.zeros(4)]
        uv, _ = cv2.projectPoints(P, v["rv"], v["tv"], v["K"], None)
        cv2.polylines(im, [uv.reshape(-1, 2).astype(np.int32)], True, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(os.path.join(OUT, "markers.jpg"), im, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return v["name"]


def cameras_plot():
    lay = layout(); W, H = lay["page_mm"]
    fig = plt.figure(figsize=(10, 7.5), dpi=170, facecolor=BG)
    ax = fig.add_subplot(111, projection="3d", facecolor=BG)
    sheet = np.array([[0, 0, 0], [W, 0, 0], [W, H, 0], [0, H, 0]])
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    ax.add_collection3d(Poly3DCollection([sheet], facecolor="#E9ECF2", edgecolor=MUTED, alpha=0.9))
    for cs in lay["corners_mm"].values():
        ax.add_collection3d(Poly3DCollection([np.c_[np.array(cs), np.full(4, 0.3)]], facecolor="#1B1E24", edgecolor="none"))
    m = trimesh.load(os.path.join(SCAN, "sam3d_fitted.stl")).simplify_quadric_decimation(face_count=3000) if hasattr(trimesh.Trimesh, "simplify_quadric_decimation") else trimesh.load(os.path.join(SCAN, "sam3d_fitted.stl"))
    try:
        ax.add_collection3d(Poly3DCollection(m.vertices[m.faces[::max(1, len(m.faces) // 4000)]], facecolor=ACC, edgecolor="none", alpha=0.95))
    except Exception:
        pass
    Cs = []
    for v in views:
        R = cv2.Rodrigues(v["rv"])[0]; C = (-R.T @ v["tv"].reshape(3)); Cs.append(C)
        ax.plot([C[0], W / 2], [C[1], H / 2], [C[2], 0], color=ACC, lw=0.8, alpha=0.35)
        # a small camera: a square facing the sheet
        f = R.T @ np.array([0, 0, 1.0]); x = R.T @ np.array([1.0, 0, 0]); y = R.T @ np.array([0, 1.0, 0]); s = 24
        q = [C + f * 30 + (sx * x + sy * y) * s for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        ax.add_collection3d(Poly3DCollection([q], facecolor=PALE, edgecolor="white", linewidths=0.6, alpha=0.95))
        for corner in q:
            ax.plot([C[0], corner[0]], [C[1], corner[1]], [C[2], corner[2]], color="white", lw=0.5, alpha=0.7)
    Cs = np.array(Cs); lo = np.minimum(Cs.min(0), [0, 0, 0]) - 20; hi = np.maximum(Cs.max(0), [W, H, 0]) + 20
    ax.set_xlim(lo[0], hi[0]); ax.set_ylim(lo[1], hi[1]); ax.set_zlim(0, hi[2])
    ax.set_box_aspect(tuple(hi - np.array([lo[0], lo[1], 0])), zoom=1.75)
    ax.view_init(elev=22, azim=-62); ax.set_axis_off()
    plt.tight_layout(pad=0); fig.savefig(os.path.join(OUT, "cameras.png"), facecolor=BG, bbox_inches="tight", pad_inches=0.02); plt.close(fig)


def masks_grid(n=6):
    idx = np.linspace(0, len(views) - 1, n).round().astype(int)
    tiles = []
    for k in idx:
        v = views[k]; im = photo(v["name"]); m = masks[k]
        if m.shape[:2] != im.shape[:2]:
            m = cv2.resize(m.astype(np.uint8), (im.shape[1], im.shape[0]), interpolation=cv2.INTER_NEAREST)
        m = (m > 0).astype(np.uint8)
        ov = im.copy(); ov[m > 0] = (0.45 * np.array(ACC_BGR) + 0.55 * im[m > 0]).astype(np.uint8)
        cs, _ = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(ov, cs, -1, (255, 255, 255), 3, cv2.LINE_AA)
        h, w = ov.shape[:2]; tw, th = 560, 420; s = max(tw / w, th / h)
        ov = cv2.resize(ov, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        y0 = (ov.shape[0] - th) // 2; x0 = (ov.shape[1] - tw) // 2
        tiles.append(ov[y0:y0 + th, x0:x0 + tw])
    gap = 16; rows = [np.hstack(sum([[t, np.full((420, gap, 3), (0x1A, 0x16, 0x14), np.uint8)] for t in tiles[r * 3:(r + 1) * 3]], [])[:-1]) for r in range(2)]
    can = np.vstack([rows[0], np.full((gap, rows[0].shape[1], 3), (0x1A, 0x16, 0x14), np.uint8), rows[1]])
    cv2.imwrite(os.path.join(OUT, "masks.jpg"), can, [cv2.IMWRITE_JPEG_QUALITY, 92])


def clear_pair_overlay():
    """The clear-handled pair: photos only (masks fill the clear holes) beside photos' edge plus SAM 3D's holes."""
    from bevell3d.tool_fingers import top_outline, handles, FingerParams
    from bevell3d.tool_geometry import most_overhead, photo_of, flatten, smooth_outline, composite_outline, find_pivot, tool_thickness
    from bevell3d.scissors_sim import pivot_of
    d = os.path.join(ROOT, "out", "real_scissors")
    hull = trimesh.load(f"{d}/hull.stl"); vq = pickle.load(open(f"{d}/views.pkl", "rb"))
    outline = top_outline(vq["views"], vq["masks"], float(hull.bounds[1][2]) / 2)
    info = handles(hull, FingerParams(), outline=outline)
    k = most_overhead(vq["views"]); v = vq["views"][k]; img = cv2.imread(photo_of(d, v["name"], vq.get("size")))
    x0, y0, x1, y1 = outline.bounds; b = (x0 - 8, y0 - 8, x1 + 8, y1 + 8); res = 0.15
    flat, _, _ = flatten(img, v, b, 3.0, res=res)
    sam = trimesh.load(f"{d}/sam3d_fitted.stl")
    pivot, toward = pivot_of(outline, info); found, _ = find_pivot(d, outline, info, tool_thickness(info))
    if found is not None: pivot = np.asarray(found, float)
    comp = smooth_outline(composite_outline(outline, sam, pivot, toward))
    def draw(geom, colour, name):
        im = flat.copy()
        for g in getattr(geom, "geoms", [geom]):
            for ring in [g.exterior] + list(g.interiors):
                pts = np.array([((p[0] - b[0]) / res, (b[3] - p[1]) / res) for p in ring.coords])
                cv2.polylines(im, [pts.astype(np.int32)], True, colour, 4, cv2.LINE_AA)
        cv2.imwrite(os.path.join(OUT, name), im, [cv2.IMWRITE_JPEG_QUALITY, 92])
    draw(outline, (90, 90, 240), "clear_masks_only.jpg")
    draw(comp, ACC_BGR, "clear_composite.jpg")


def pivot_photo():
    """The dark pair's photo from above, flattened to scale, its outline and the pivot screw circled."""
    from bevell3d.tool_fingers import top_outline, handles, FingerParams
    from bevell3d.tool_geometry import most_overhead, photo_of, flatten, find_pivot, tool_thickness
    hull = trimesh.load(f"{SCAN}/hull.stl")
    outline = top_outline(views, masks, float(hull.bounds[1][2]) / 2)
    info = handles(hull, FingerParams(), outline=outline)
    k = most_overhead(views); v = views[k]; img = cv2.imread(photo_of(SCAN, v["name"], vp.get("size")))
    x0, y0, x1, y1 = outline.bounds; b = (x0 - 8, y0 - 8, x1 + 8, y1 + 8); res = 0.15
    flat, _, _ = flatten(img, v, b, 3.0, res=res)
    found, how = find_pivot(SCAN, outline, info, tool_thickness(info))
    cv2.imwrite(os.path.join(OUT, "top_photo.jpg"), flat, [cv2.IMWRITE_JPEG_QUALITY, 92])
    im = flat.copy()
    if found is not None:
        c = (int((found[0] - b[0]) / res), int((b[3] - found[1]) / res)); r = int(max(how["radius_mm"], 3.0) / res)
        cv2.circle(im, c, r + 10, ACC_BGR, 5, cv2.LINE_AA)
        cv2.line(im, (c[0] - r - 40, c[1]), (c[0] - r - 16, c[1]), ACC_BGR, 5, cv2.LINE_AA)
        cv2.line(im, (c[0] + r + 16, c[1]), (c[0] + r + 40, c[1]), ACC_BGR, 5, cv2.LINE_AA)
        cv2.line(im, (c[0], c[1] - r - 40), (c[0], c[1] - r - 16), ACC_BGR, 5, cv2.LINE_AA)
        cv2.line(im, (c[0], c[1] + r + 16), (c[0], c[1] + r + 40), ACC_BGR, 5, cv2.LINE_AA)
    cv2.imwrite(os.path.join(OUT, "pivot.jpg"), im, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return how


def clip_section():
    """A section through one clip with the loop in it, dark-themed."""
    from bevell3d.tool_fingers import top_outline, handles, FingerParams
    from bevell3d.tool_geometry import smooth_outline
    from bevell3d.custom_jaws import loop_clip_mesh, _extrude, PRINT_CLEARANCE_MM as CL
    from shapely.geometry import Polygon, Point
    hull = trimesh.load(f"{SCAN}/hull.stl")
    outline = top_outline(views, masks, float(hull.bounds[1][2]) / 2)
    info = handles(hull, FingerParams(), outline=outline)
    h = info["handles"][0]; o = smooth_outline(outline)
    body, rep, _ = loop_clip_mesh(o, h, arm_top=True)
    body = trimesh.boolean.difference([body, _extrude(o.buffer(CL), h["z_mm"] - CL, h["z_mm"] + h["thickness_mm"] + CL)], engine="manifold")
    c = np.array(h["centre_mm"]); hole = min([Polygon(r) for r in o.interiors if Polygon(r).area > 20], key=lambda g: g.distance(Point(c)))
    hc = np.array(hole.centroid.coords[0]); radial = (c - hc) / np.linalg.norm(c - hc); tang = np.array([-radial[1], radial[0], 0.0])
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=170, facecolor=BG); ax.set_facecolor(BG)
    z0 = h["z_mm"]
    for e in body.section(plane_origin=[c[0], c[1], h["z_mm"]], plane_normal=tang).discrete:
        ax.fill(e[:, 2] - z0, -((e[:, :2] - c) @ radial), color=ACC, alpha=0.95, lw=0)
    ring = o.intersection(Point(c).buffer(0.6))
    # the loop's section: the ring's radial span at the grasp point, its measured thickness
    pts = np.array([(c + radial * s) for s in np.linspace(-12, 12, 481)])
    inside = [o.contains(Point(p)) for p in pts]; s_in = np.linspace(-12, 12, 481)[np.array(inside)]
    if len(s_in):
        lo, hi = s_in.min(), s_in.max()
        ax.add_patch(plt.Rectangle((0, -hi), h["thickness_mm"], hi - lo, facecolor="#C8CCD4", edgecolor="none", alpha=0.95))
        t = h["thickness_mm"]
        ax.set_xlim(-3, t + 3); ax.set_ylim(-hi - 2.6, -lo + 2.2)
    ax.set_aspect("equal"); ax.axis("off")
    plt.tight_layout(pad=0.2); fig.savefig(os.path.join(OUT, "clip_section.png"), facecolor=BG); plt.close(fig)
    return rep


def sim_frames():
    vid = os.path.join(SCAN, "jaws", "sim_three_quarter.mp4")
    cap = cv2.VideoCapture(vid); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); out = []
    for t in (0, n // 2):
        cap.set(cv2.CAP_PROP_POS_FRAMES, t); ok, f = cap.read(); out.append(f)
    for name, f in zip(("sim_closed.jpg", "sim_open.jpg"), out):
        h, w = f.shape[:2]; f = f[int(h * 0.12):int(h * 0.88), int(w * 0.1):int(w * 0.9)]
        cv2.imwrite(os.path.join(OUT, name), f, [cv2.IMWRITE_JPEG_QUALITY, 92])


if __name__ == "__main__":
    which = sys.argv[1:] or ["contact", "markers", "cameras", "masks", "clear", "pivot", "clip", "sim"]
    if "contact" in which: contact_sheet()
    if "markers" in which: print("markers on", markers_photo())
    if "cameras" in which: cameras_plot()
    if "masks" in which: masks_grid()
    if "clear" in which: clear_pair_overlay()
    if "pivot" in which: print("pivot", pivot_photo())
    if "clip" in which: print("clip", clip_section())
    if "sim" in which: sim_frames()
    print("done")
