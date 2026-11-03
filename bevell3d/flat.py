"""Flat route: straighten a top-down photo with the A4 sheet, measure the part in mm."""
import sys, numpy as np, cv2
from PIL import Image
from .sam_client import segment
from . import carve as C

PX_PER_MM = 6.0

def run(n, prompt):
    path = f"raw/IMG_{n}.jpg"
    im, s, obj = segment(path, prompt)
    _, _, sheet = segment(path, "sheet of paper")
    obj = max(obj, key=lambda r: r["mask"].sum())["mask"]; sheet = max(sheet, key=lambda r: r["mask"].sum())["mask"]
    q = C.sheet_quad(sheet, obj)
    o = C.orderings(q)[0]
    dst = np.array([[0, 0], [297, 0], [297, 210], [0, 210]], np.float32) * PX_PER_MM
    Hm = cv2.getPerspectiveTransform(o.astype(np.float32), dst)
    size = (int(297 * PX_PER_MM), int(210 * PX_PER_MM))
    rgb = cv2.warpPerspective(np.array(im)[:, :, ::-1], Hm, size)
    m = cv2.warpPerspective(obj.astype(np.uint8) * 255, Hm, size) > 127
    cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea)
    (cx, cy), r = cv2.minEnclosingCircle(c)
    pts = c.reshape(-1, 2).astype(float)
    # least-squares circle (Kasa)
    A = np.c_[2 * pts, np.ones(len(pts))]; b = (pts ** 2).sum(1)
    sol = np.linalg.lstsq(A, b, rcond=None)[0]; r_ls = np.sqrt(sol[2] + sol[0] ** 2 + sol[1] ** 2)
    x, y, w, h = cv2.boundingRect(c)
    cv2.drawContours(rgb, [c], -1, (0, 0, 255), 3)
    cv2.circle(rgb, (int(sol[0]), int(sol[1])), int(r_ls), (0, 200, 0), 2)
    crop = rgb[max(0, y - 60):y + h + 60, max(0, x - 60):x + w + 60]
    cv2.imwrite(f"medal_{n}_flat.jpg", crop)
    print(n, f"diameter (circle fit) {2 * r_ls / PX_PER_MM:.1f} mm, bounding box {w / PX_PER_MM:.1f} x {h / PX_PER_MM:.1f} mm")

if __name__ == "__main__":
    for n in sys.argv[2:]:
        run(n, sys.argv[1])
