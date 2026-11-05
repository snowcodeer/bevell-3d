"""Behind-the-scenes clip: SAM 3.1 finding the scissors in every photo (the dark pair).

    .venv/bin/python docs/video/make_segmentation_video.py            # 1920x1080
    .venv/bin/python docs/video/make_segmentation_video.py --vertical # 1080x1920

Each placed photo appears, the sheet's squares are drawn back through its measured camera (first
three), then the mask sweeps in behind a scan line. It ends on a grid of every photo and mask.
"""
import json, os, pickle, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCAN = os.path.join(ROOT, "out", "black_scissors")
FONTS = os.environ.get("BEVELL_FONTS", "/private/tmp/claude-501/-Users-nataliechan-Projects-bevell/a2b2193e-bc31-4c51-853a-b32a3ad2f03a/scratchpad/fonts")
VERTICAL = "--vertical" in sys.argv
W, H = (1080, 1920) if VERTICAL else (1920, 1080)
FPS = 30
BG = np.array([0x14, 0x16, 0x1A], np.uint8)
ACC = np.array([0x39, 0x5A, 0xF6], np.float32)
ACC_LIGHT = (0x64, 0x7E, 0xF8)
PALE = (0x80, 0x95, 0xF9)
MUTED = (0x9A, 0xA0, 0xAA)
PER, XFADE, END = 1.2, 0.25, 3.0

vp = pickle.load(open(os.path.join(SCAN, "views.pkl"), "rb"))
views, masks = vp["views"], vp["masks"]
lay = json.load(open(os.path.join(ROOT, "assets", "capture_sheet_layout.json")))
font = lambda w, s: ImageFont.truetype(os.path.join(FONTS, f"Inter-{w}.ttf"), s)
title_font = ImageFont.truetype(os.path.join(FONTS, "Outfit-600.ttf"), 34 if not VERTICAL else 40)

# The photo's box on the frame
BOX_W, BOX_H = (W - 160, H - 420) if VERTICAL else (W - 240, H - 220)
BOX_Y = 170 if VERTICAL else 90


def ease(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def rounded(h, w, r=22):
    m = np.zeros((h, w), np.uint8)
    cv2.rectangle(m, (r, 0), (w - r, h), 255, -1); cv2.rectangle(m, (0, r), (w, h - r), 255, -1)
    for cx, cy in ((r, r), (w - r, r), (r, h - r), (w - r, h - r)):
        cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    return m.astype(np.float32)[..., None] / 255


def prepare(k):
    v = views[k]
    im = cv2.cvtColor(cv2.imread(os.path.join(SCAN, "photos", v["name"] + ".jpg")), cv2.COLOR_BGR2RGB)
    m = masks[k].astype(np.uint8)
    if m.shape[:2] != im.shape[:2]:
        m = cv2.resize(m, (im.shape[1], im.shape[0]), interpolation=cv2.INTER_NEAREST)
    # the sheet's squares, drawn back through this photo's camera
    sq = np.zeros(im.shape[:2], np.uint8)
    for cs in lay["corners_mm"].values():
        P = np.c_[np.array(cs, float), np.zeros(4)]
        uv, _ = cv2.projectPoints(P, v["rv"], v["tv"], v["K"], None)
        cv2.polylines(sq, [uv.reshape(-1, 2).astype(np.int32)], True, 255, 7, cv2.LINE_AA)
    h, w = im.shape[:2]; s = min(BOX_W / w, BOX_H / h)
    size = (int(w * s), int(h * s))
    im = cv2.resize(im, size, interpolation=cv2.INTER_AREA).astype(np.float32)
    m = cv2.resize(m * 255, size, interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255
    sq = cv2.resize(sq, size, interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    edge = np.zeros(size[::-1], np.uint8)
    cs, _ = cv2.findContours((m > 0.5).astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(edge, cs, -1, 255, 3, cv2.LINE_AA)
    return {"im": im, "mask": m, "edge": edge.astype(np.float32) / 255, "sq": sq, "name": v["name"]}


def photo_layer(p, t, squares):
    """The photo at time t (s) into its beat: squares (first photos), then the mask's sweep."""
    im = p["im"].copy(); h, w = im.shape[:2]
    if squares:
        a = ease((t - 0.05) / 0.25) * (1 - 0.7 * ease((t - 0.75) / 0.3))
        im = im * (1 - a * p["sq"][..., None]) + np.array(ACC_LIGHT, np.float32) * a * p["sq"][..., None]   # white vanished on the white sheet
    sweep = ease((t - 0.3) / 0.55)
    cut = int(sweep * (h + 40)) - 20
    rows = (np.arange(h) <= cut).astype(np.float32)[:, None]
    fill = p["mask"] * rows * 0.42
    im = im * (1 - fill[..., None]) + ACC * fill[..., None]
    edge = p["edge"] * rows
    im = im * (1 - edge[..., None]) + np.array(ACC_LIGHT, np.float32) * edge[..., None]
    if 0 < cut < h and sweep < 1:                       # the scan line
        y0, y1 = max(cut - 2, 0), min(cut + 2, h)
        glow = np.exp(-((np.arange(h) - cut) / 10.0) ** 2)[:, None, None] * 0.35
        im = im * (1 - glow) + np.array(ACC_LIGHT, np.float32) * glow
        im[y0:y1] = np.array(ACC_LIGHT, np.float32)
    return im


def place(frame, layer, alpha=1.0):
    h, w = layer.shape[:2]
    x0 = (W - w) // 2; y0 = BOX_Y + (BOX_H - h) // 2
    r = rounded(h, w) * alpha
    region = frame[y0:y0 + h, x0:x0 + w]
    frame[y0:y0 + h, x0:x0 + w] = region * (1 - r) + layer * r
    return frame


def chrome(img, k=None, n=None, end=False):
    d = ImageDraw.Draw(img)
    d.text((48, 36) if not VERTICAL else (48, 60), "Bevell 3D", font=title_font, fill=(255, 255, 255))
    cap = "SAM 3.1 · finding the scissors in every photo"
    f = font(600, 30 if not VERTICAL else 34)
    x, y = (48, H - 74) if not VERTICAL else (48, H - 150)
    pill_f = font(600, 20)
    pw = d.textlength("Meta", font=pill_f) + 24
    d.rounded_rectangle((x, y + 2, x + pw, y + 34), radius=17, fill=(0x26, 0x30, 0x5E))
    d.text((x + 12, y + 6), "Meta", font=pill_f, fill=PALE)
    d.text((x + pw + 14, y), cap, font=f, fill=(255, 255, 255))
    cf = font(500, 26 if not VERTICAL else 30)
    label = f"{n} photos · {n} masks" if end else f"Photo {k + 1} of {n}"
    tw = d.textlength(label, font=cf)
    d.text(((W - 48 - tw), 44 if not VERTICAL else 68), label, font=cf, fill=MUTED)
    return img


def grid_frame(ps):
    n = len(ps)
    cols, rows = (7, 2) if not VERTICAL else (3, 5)
    gap = 14
    gw, gh = BOX_W, BOX_H
    tw = (gw - (cols - 1) * gap) // cols; th = int(tw * 4 / 3)
    if rows * th + (rows - 1) * gap > gh:
        th = (gh - (rows - 1) * gap) // rows; tw = int(th * 3 / 4)
    totw = cols * tw + (cols - 1) * gap; toth = rows * th + (rows - 1) * gap
    can = np.zeros((H, W, 3), np.float32) + BG
    for i, p in enumerate(ps):
        r, c = divmod(i, cols)
        if r >= rows:
            break
        layer = photo_layer(p, 10.0, False)
        t = cv2.resize(layer, (tw, th), interpolation=cv2.INTER_AREA)
        x0 = (W - totw) // 2 + c * (tw + gap); y0 = BOX_Y + (BOX_H - toth) // 2 + r * (th + gap)
        rr = rounded(th, tw, 12)
        can[y0:y0 + th, x0:x0 + tw] = can[y0:y0 + th, x0:x0 + tw] * (1 - rr) + t * rr
    return can


def main():
    ps = [prepare(k) for k in range(len(views))]
    n = len(ps)
    out = os.path.join(ROOT, "docs", "video", "segmentation_vertical.mp4" if VERTICAL else "segmentation.mp4")
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                           "-preset", "medium", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    base = np.zeros((H, W, 3), np.float32) + BG
    prev_layer = None
    per = int(PER * FPS); xf = int(XFADE * FPS)
    for k, p in enumerate(ps):
        for f in range(per):
            t = f / FPS
            frame = base.copy()
            cur = photo_layer(p, t, k < 3)
            if prev_layer is not None and f < xf:          # cross-fade from the last photo
                a = ease(f / xf)
                frame = place(frame, prev_layer, 1 - a)
                frame = place(frame, cur, a)
            else:
                frame = place(frame, cur, ease(f / xf) if k == 0 else 1.0)
            img = chrome(Image.fromarray(frame.clip(0, 255).astype(np.uint8)), k, n)
            ff.stdin.write(np.asarray(img).tobytes())
        prev_layer = photo_layer(p, PER, k < 3)
    grid = grid_frame(ps)
    last = place(base.copy(), prev_layer)
    for f in range(int(END * FPS)):
        a = ease(f / (0.5 * FPS))
        frame = last * (1 - a) + grid * a
        img = chrome(Image.fromarray(frame.clip(0, 255).astype(np.uint8)), n - 1, n, end=a > 0.5)
        ff.stdin.write(np.asarray(img).tobytes())
    ff.stdin.close(); ff.wait()
    print(out, f"{(n * per + int(END * FPS)) / FPS:.1f} s")


if __name__ == "__main__":
    main()
