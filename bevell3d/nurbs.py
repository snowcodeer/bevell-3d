"""A freeform scan as smooth NURBS surfaces, not triangles.

The scan is quad-remeshed (Blender's QuadriFlow), and every quad becomes one bicubic Bezier
patch approximating the Catmull-Clark limit surface of that quad mesh (Loop and Schaefer,
"Approximating Catmull-Clark subdivision surfaces with bicubic patches", 2008):

- interior points: (n v + 2 (prev + next) + opposite) / (n + 5), for each corner v of valence n;
- edge points: the mean of the two interior points either side of the edge;
- corner points: the mean of the interior points round the vertex (its limit position).

Patches share their boundary control points, so they meet exactly and sew into one solid. They
are tangent-continuous where four quads meet and nearly so at the few vertices where three or
five do. The result is a STEP of a few hundred to a few thousand Bezier faces that a CAD package
opens as a smooth body to cut, shell or fillet. It is not a parametric feature tree.

    python -m bevell3d.nurbs model.stl out.step [--quads 1200]
"""
import os, subprocess, sys, tempfile
import numpy as np

BLENDER = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
_REMESH = '''
import bpy, sys
a = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=a[0])
ob = bpy.context.selected_objects[0]; bpy.context.view_layer.objects.active = ob
if len(ob.data.polygons) > int(a[3]):          # QuadriFlow gives up on very dense meshes
    ob.data.remesh_voxel_size = max(ob.dimensions) / 220
    bpy.ops.object.voxel_remesh()
bpy.ops.object.quadriflow_remesh(target_faces=int(a[2]), use_preserve_sharp=False, use_mesh_symmetry=False, smooth_normals=True)
bpy.ops.wm.obj_export(filepath=a[1], export_selected_objects=True, export_materials=False, export_normals=False,
                      export_uv=False, forward_axis="Y", up_axis="Z")
'''


def quad_remesh(stl_path, quads=1200, blender=BLENDER, dense=120000):
    """(vertices, quads) from QuadriFlow in a background Blender; a mesh over `dense` faces is
    first voxel-remeshed there, which keeps it closed and manifold as QuadriFlow needs (decimating
    it in trimesh did not, and QuadriFlow failed on all three test objects)."""
    with tempfile.TemporaryDirectory() as d:
        script, obj = os.path.join(d, "remesh.py"), os.path.join(d, "quads.obj")
        open(script, "w").write(_REMESH)
        subprocess.run([blender, "-b", "-P", script, "--", os.path.abspath(stl_path), obj, str(quads), str(dense)],
                       check=True, capture_output=True, timeout=300)
        return read_quads(obj)


def read_quads(obj_path):
    v, f = [], []
    for line in open(obj_path):
        if line.startswith("v "):
            v.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("f "):
            f.append([int(x.split("/")[0]) - 1 for x in line.split()[1:]])
    if any(len(q) != 4 for q in f):
        raise ValueError(f"QuadriFlow did not remesh: {sum(len(q) != 4 for q in f)} faces are not quads")
    return np.array(v), np.array(f)


def limit_points(V, F):
    """Where the smooth surface passes each quad-mesh vertex (its Catmull-Clark limit point)."""
    V = np.asarray(V, float); F = np.asarray(F)
    n = np.bincount(F.ravel(), minlength=len(V))[F][..., None]
    interior = (n * V[F] + 2 * (V[np.roll(F, -1, 1)] + V[np.roll(F, 1, 1)]) + V[np.roll(F, 2, 1)]) / (n + 5)
    out = np.zeros_like(V); count = np.zeros(len(V))
    np.add.at(out, F.ravel(), interior.reshape(-1, 3)); np.add.at(count, F.ravel(), 1)
    return out / np.maximum(count, 1)[:, None]


def fit_cage(V, F, iterations=4):
    """Move the control points so the surface passes through the remeshed scan's vertices: the
    limit surface sits inside its cage on convex parts, and Mario came out 4% small."""
    target = np.asarray(V, float); C = target.copy()
    for _ in range(iterations):
        C += target - limit_points(C, F)
    return C


def bezier_nets(V, F):
    """A 4 x 4 control net per quad, indexed [face, i along the first edge, j along the last]."""
    V = np.asarray(V, float); F = np.asarray(F)
    valence = np.bincount(F.ravel(), minlength=len(V))
    # interior[f, k]: the interior point of face f at its corner k
    nxt, prv, opp = np.roll(F, -1, 1), np.roll(F, 1, 1), np.roll(F, 2, 1)
    n = valence[F][..., None]
    interior = (n * V[F] + 2 * (V[nxt] + V[prv]) + V[opp]) / (n + 5)
    corner = np.zeros_like(V); count = np.zeros(len(V))
    np.add.at(corner, F.ravel(), interior.reshape(-1, 3)); np.add.at(count, F.ravel(), 1)
    corner /= np.maximum(count, 1)[:, None]
    # For each directed edge a->b in a face, the interior point at a; its twin edge b->a lives in
    # the neighbouring face, whose interior point at a is the one we average with.
    at = {}
    for fi, q in enumerate(F):
        for k in range(4):
            at[(q[k], q[(k + 1) % 4])] = interior[fi, k]       # interior at q[k], beside edge q[k]->q[k+1]
            at[(q[k], q[(k - 1) % 4], "back")] = interior[fi, k]
    def edge_point(a, b):
        """The control point on edge a-b next to a: mean of the interior points at a either side."""
        p1 = at.get((a, b)); p2 = at.get((a, b, "back"))
        if p1 is None or p2 is None:
            raise ValueError(f"edge {a}-{b} is on a boundary: the quad mesh is not closed")
        return (p1 + p2) / 2
    nets = np.zeros((len(F), 4, 4, 3))
    for fi, (a, b, c, d) in enumerate(F):
        P = nets[fi]
        P[0, 0], P[3, 0], P[3, 3], P[0, 3] = corner[a], corner[b], corner[c], corner[d]
        P[1, 0], P[2, 0] = edge_point(a, b), edge_point(b, a)
        P[3, 1], P[3, 2] = edge_point(b, c), edge_point(c, b)
        P[1, 3], P[2, 3] = edge_point(d, c), edge_point(c, d)
        P[0, 1], P[0, 2] = edge_point(a, d), edge_point(d, a)
        P[1, 1], P[2, 1], P[2, 2], P[1, 2] = interior[fi, 0], interior[fi, 1], interior[fi, 2], interior[fi, 3]
    return nets


def nets_to_solid(nets, tol=1e-4):
    """Sew the Bezier patches into one closed solid."""
    import cadquery as cq
    from OCP.Geom import Geom_BezierSurface
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.gp import gp_Pnt
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopoDS import TopoDS
    sew = BRepBuilderAPI_Sewing(tol)
    for P in nets:
        arr = TColgp_Array2OfPnt(1, 4, 1, 4)
        for i in range(4):
            for j in range(4):
                arr.SetValue(i + 1, j + 1, gp_Pnt(*map(float, P[i, j])))
        sew.Add(BRepBuilderAPI_MakeFace(Geom_BezierSurface(arr), 1e-6).Face())
    sew.Perform()
    shape = sew.SewedShape()
    if shape.ShapeType() != TopAbs_SHELL:
        raise ValueError(f"the patches sewed into a {shape.ShapeType()}, not one shell")
    solid = cq.Solid(ShapeFix_Solid().SolidFromShell(TopoDS.Shell_s(shape)))
    if solid.Volume() < 0:
        solid = cq.Solid(solid.wrapped.Reversed())
    return solid


def prepare(mesh):
    """One closed surface: the largest piece, remeshed closed if it is not (SAM 3D's mouse is
    a hollow shell)."""
    from .cad import main_body, clean_body
    body = main_body(mesh)
    return body if body.is_watertight else clean_body(body)


def quads_for(mesh):
    """About one patch per 10 mm² of surface (3 mm across), between 800 and 4,000: the clock's
    1,200 lost 0.6 mm of detail against its scan."""
    return int(np.clip(mesh.area / 10.0, 800, 4000))


def scan_to_nurbs(stl_path, step_path=None, quads=None):
    """Returns (solid, report). The report measures the surface against the scan."""
    import trimesh
    scan = prepare(trimesh.load(stl_path))
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        prepared = f.name
    scan.export(prepared)
    quads = quads or quads_for(scan)
    errors = []
    try:
        # QuadriFlow now and then leaves a hole at one density and not at another (the mouse at
        # 3,000 quads), so try sparser before giving up.
        for q in (quads, int(quads * 0.6), int(quads * 0.35)):
            try:
                V, F = quad_remesh(prepared, max(q, 300))
                solid = nets_to_solid(bezier_nets(fit_cage(V, F), F))
                if solid.isValid():
                    break
                errors.append(f"{q} quads: invalid solid")
            except (ValueError, subprocess.SubprocessError) as e:
                errors.append(f"{q} quads: {e}")
        else:
            raise ValueError("no smooth surface: " + "; ".join(errors))
    finally:
        os.remove(prepared)
    vs, fs = solid.tessellate(0.05, 0.2)
    m = trimesh.Trimesh(np.array([v.toTuple() for v in vs]), np.array(fs))
    to_scan = np.abs(trimesh.proximity.ProximityQuery(scan).signed_distance(m.sample(20000)))
    from_scan = np.abs(trimesh.proximity.ProximityQuery(m).signed_distance(scan.sample(20000)))
    report = {"patches": int(len(F)), "valid": bool(solid.isValid()), "volume_cm3": round(solid.Volume() / 1000, 1),
              "scan_volume_cm3": round(float(scan.volume) / 1000, 1),
              "off_scan_mean_mm": round(float(np.r_[to_scan, from_scan].mean()), 2),
              "off_scan_p95_mm": round(float(np.percentile(np.r_[to_scan, from_scan], 95)), 2),
              "extraordinary_vertices": int(np.sum(np.bincount(F.ravel()) != 4)), "retries": errors}
    if step_path:
        import cadquery as cq
        cq.exporters.export(cq.Workplane().add(solid), step_path)
    return solid, report


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser(); ap.add_argument("stl"); ap.add_argument("step"); ap.add_argument("--quads", type=int)
    a = ap.parse_args()
    print(json.dumps(scan_to_nurbs(a.stl, a.step, a.quads)[1], indent=1))
