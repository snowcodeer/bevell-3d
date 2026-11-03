"""Projecting points and meshes into calibrated photos."""
import numpy as np, cv2


def project(pts, view):
    p, _ = cv2.projectPoints(np.asarray(pts, np.float64), view["rv"], view["tv"], view["K"], None)
    return p.reshape(-1, 2)


def silhouette(mesh, view, size, scale=1.0):
    """Filled outline of a mesh in a photo of `size` (w, h), optionally downscaled."""
    w, h = int(size[0] * scale), int(size[1] * scale)
    out = np.zeros((h, w), np.uint8)
    uv = np.round(project(mesh.vertices, view) * scale).astype(np.int32)
    # One triangle at a time: fillPoly given them all at once fills by even-odd, so where
    # the front and back of the mesh overlap they cancel and the outline comes out holed.
    for tri in uv[mesh.faces]:
        cv2.fillConvexPoly(out, tri, 1)
    return out.astype(bool)


def iou(a, b):
    return float((a & b).sum() / max(1, (a | b).sum()))
