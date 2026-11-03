"""SAM 3D on one 2 Nov AirPods photo, fitted to all eight 2 Nov photos (old A4-edge cameras).

    .venv/bin/python -m tools.sam3d_prototype 1746
"""
import io, json, pickle, sys
import numpy as np, trimesh
from bevell3d.fit import fit
from bevell3d.holder import make_holder, seated
from bevell3d.project import silhouette, iou
from bevell3d.render import render, render_scene

P = "out/prototype-2nov"
T = "out/sam3d_test"


def main(n="1746"):
    import modal
    Sam3D = modal.Cls.from_name("bevell-sam3d", "Sam3D")
    res = Sam3D().reconstruct.remote(open(f"{T}/IMG_{n}.jpg", "rb").read(), open(f"{T}/IMG_{n}_mask.png", "rb").read())
    open(f"{T}/sam3d_{n}.glb", "wb").write(res["glb"])
    scene = trimesh.load(io.BytesIO(res["glb"]), file_type="glb")
    gen = scene.dump(concatenate=True) if isinstance(scene, trimesh.Scene) else scene
    print("SAM 3D mesh:", len(gen.vertices), "vertices, extents (its own units)", np.round(gen.extents, 3), "pose", res["pose"])
    cache = pickle.load(open(f"{P}/cache_airpods.pkl", "rb"))
    views = pickle.load(open(f"{P}/airpods_views.pkl", "rb"))
    masks = [cache[str(v["n"])]["obj"] for v in views]
    size = cache[str(views[0]["n"])]["size"]
    hull = trimesh.load(f"{P}/airpods_hull.stl")
    fitted, rep = fit(gen, views, masks, size, guide=hull)
    rep["agreement_full_res"] = round(float(np.mean([iou(silhouette(fitted, v, size), m) for v, m in zip(views, masks)])), 3)
    rep["hull_agreement_full_res"] = round(float(np.mean([iou(silhouette(hull, v, size), m) for v, m in zip(views, masks)])), 3)
    print(json.dumps(rep, indent=1, default=float))
    fitted.export(f"{T}/sam3d_{n}_fitted.stl")
    render(fitted, f"{T}/sam3d_{n}_fitted.png", "SAM 3D, fitted to the 2 Nov photos")
    holder, hrep = make_holder(fitted)
    holder.export(f"{T}/sam3d_{n}_holder.stl")
    seated(fitted).export(f"{T}/sam3d_{n}_seated.stl")
    render_scene([(holder, (0.85, 0.85, 0.88)), (seated(fitted), (0.22, 0.35, 0.95))], f"{T}/sam3d_{n}_holder.png", "In its holder")
    print("holder", hrep)


if __name__ == "__main__":
    main(*sys.argv[1:])
