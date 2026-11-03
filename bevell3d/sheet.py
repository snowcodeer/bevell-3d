"""The capture sheet: ArUco markers round an A4 page, and where each one is in the world.

World frame: millimetres, origin at the page's top-left corner as printed, X along the
long edge, Y towards the top edge (so Y = 210 - page y), Z up out of the paper. The object
sits on the paper at Z >= 0.
"""
import json, os
import numpy as np, cv2
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT_PATH = os.path.join(HERE, "..", "assets", "capture_sheet_layout.json")


def load_layout(path=LAYOUT_PATH):
    d = json.load(open(path))
    page_w, page_h = d["page_mm"]
    world = {int(k): np.array([[x, page_h - y, 0.0] for x, y in v], np.float64) for k, v in d["corners_mm"].items()}
    return {"dictionary": getattr(cv2.aruco, d["dictionary"]), "marker_mm": d["marker_mm"],
            "page_mm": (page_w, page_h), "world": world, "page_corners": d["corners_mm"]}


def raster(ppm=10.0, layout=None):
    """The sheet as a white image at `ppm` pixels per mm (what is printed)."""
    L = layout or load_layout()
    w, h = (round(v * ppm) for v in L["page_mm"])
    img = np.full((h, w), 255, np.uint8)
    dic = cv2.aruco.getPredefinedDictionary(L["dictionary"])
    side = round(L["marker_mm"] * ppm)
    for mid, c in L["page_corners"].items():
        x0, y0 = (round(v * ppm) for v in c[0])
        img[y0:y0 + side, x0:x0 + side] = cv2.aruco.generateImageMarker(dic, int(mid), side, borderBits=1)
    return img


def make_pdf(out_path, ppm=20.0, layout=None):
    """A4 PDF at true size. Print at 100% (no fit-to-page); every marker measures 22 mm."""
    Image.fromarray(raster(ppm, layout)).save(out_path, "PDF", resolution=ppm * 25.4)
