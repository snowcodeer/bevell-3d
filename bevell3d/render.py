"""Three-view preview of a mesh, with its size in mm in the title."""
import sys
import numpy as np, trimesh, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

VIEWS = [(25, -60), (25, 30), (85, -90)]


def render(mesh, out_png, title=None, colour=(0.22, 0.35, 0.95), max_faces=6000):
    m = trimesh.load(mesh) if isinstance(mesh, str) else mesh
    if len(m.faces) > max_faces:
        m = m.simplify_quadric_decimation(face_count=max_faces)
    fig = plt.figure(figsize=(12, 4))
    lo, hi = m.bounds; c = (lo + hi) / 2; r = (hi - lo).max() / 2
    light = np.clip(m.face_normals @ np.array([0.3, -0.4, 0.85]), 0.15, 1)
    for i, (el, az) in enumerate(VIEWS):
        ax = fig.add_subplot(1, 3, i + 1, projection="3d")
        pc = Poly3DCollection(m.vertices[m.faces], alpha=1.0)
        pc.set_facecolor(np.c_[colour[0] * light, colour[1] * light, colour[2] * light, np.ones_like(light)])
        pc.set_edgecolor("none")
        ax.add_collection3d(pc)
        ax.set_xlim(c[0] - r, c[0] + r); ax.set_ylim(c[1] - r, c[1] + r); ax.set_zlim(lo[2], lo[2] + 2 * r)
        ax.view_init(el, az); ax.set_box_aspect((1, 1, 1)); ax.set_axis_off()
    ext = hi - lo
    fig.suptitle(f"{title or ''}  {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm".strip())
    plt.tight_layout(); plt.savefig(out_png, dpi=90); plt.close(fig)


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2], sys.argv[1])
