"""A CAD feature tree that both CadQuery and Fusion 360 can build.

Muse Spark writes the tree as data, not code: named parameters (mm or degrees) and steps
whose sizes are expressions in those parameters, such as "cap_d / 2". Nothing the model
writes is executed; expressions are parsed and evaluated here.

    {"parameters": [{"name": "body_d", "value": 60, "min": 40, "max": 80, "what": "..."}],
     "steps": [
       {"id": "body", "op": "revolve", "profile": [["0", "0"], ["body_d/2", "0"], ...]},
       {"id": "cap",  "op": "extrude", "shape": {"circle": {"d": "cap_d"}}, "from_z": "body_h", "height": "cap_h"},
       {"id": "hollow", "op": "shell", "thickness": "wall", "open": "top"},
       {"id": "handle", "op": "sweep", "section": {"circle": {"d": "grip"}},
        "path": {"plane": "XZ", "points": [["r", "z1"], ["r + reach", "zm"], ["r", "z2"]]}},
       {"id": "soften", "op": "fillet", "edges": "top", "radius": "lip_r"}]}

Steps: revolve (a closed (r, z) profile turned about Z), extrude (a shape on a plane at
height from_z, mode add or cut), loft (shapes at heights), sweep (a section along a smooth
path in the XZ or YZ plane), shell (hollow, open at the top or not), fillet and chamfer
(edges: top, bottom, vertical or all). Shapes: circle {d}, rect {w, l}, ellipse {w, l},
polygon [[x, y], ...]; any shape takes "at": [x, y].
"""
import ast, json, math, operator
import numpy as np

OPS = {"revolve", "extrude", "loft", "sweep", "shell", "fillet", "chamfer"}
EDGES = {"top", "bottom", "vertical", "all"}
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow}
_FUN = {"min": min, "max": max, "sqrt": math.sqrt, "sin": lambda d: math.sin(math.radians(d)),
        "cos": lambda d: math.cos(math.radians(d)), "tan": lambda d: math.tan(math.radians(d)), "abs": abs}


def ev(expr, p):
    """Evaluate an expression in the parameters: numbers, names, + - * / **, min max sqrt sin cos tan abs."""
    if isinstance(expr, (int, float)):
        return float(expr)

    def go(n):
        if isinstance(n, ast.Expression):
            return go(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.Name):
            if n.id not in p:
                raise ValueError(f"unknown parameter {n.id!r}")
            return float(p[n.id])
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            return _BIN[type(n.op)](go(n.left), go(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return -go(n.operand) if isinstance(n.op, ast.USub) else go(n.operand)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUN and not n.keywords:
            return float(_FUN[n.func.id](*[go(a) for a in n.args]))
        raise ValueError(f"not allowed in an expression: {ast.dump(n)[:60]}")
    return go(ast.parse(str(expr), mode="eval"))


def validate(tree):
    """Raise ValueError with a message Muse Spark can act on."""
    names = {q["name"] for q in tree.get("parameters", [])}
    if not tree.get("steps"):
        raise ValueError("the tree has no steps")
    if tree["steps"][0].get("op") not in ("revolve", "extrude", "loft", "sweep"):
        raise ValueError("the first step must make a solid: revolve, extrude, loft or sweep")
    for q in tree["parameters"]:
        if not (q["min"] <= q["value"] <= q["max"]):
            raise ValueError(f"parameter {q['name']}: value {q['value']} is outside [{q['min']}, {q['max']}]")
    p = {q["name"]: q["value"] for q in tree["parameters"]}
    for s in tree["steps"]:
        if s.get("op") not in OPS:
            raise ValueError(f"step {s.get('id')}: unknown op {s.get('op')!r}; use one of {sorted(OPS)}")
        if s["op"] in ("fillet", "chamfer") and s.get("edges") not in EDGES:
            raise ValueError(f"step {s.get('id')}: edges must be one of {sorted(EDGES)}")
        for e in _exprs(s):
            ev(e, p)
    return names


def _exprs(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in ("id", "op", "mode", "edges", "open", "plane"):
                yield from _exprs(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _exprs(v)
    elif isinstance(obj, (str, int, float)):
        yield obj


# --- CadQuery ---------------------------------------------------------------------------------

def _shape_cq(wp, shape, p):
    at = [ev(a, p) for a in shape.get("at", [0, 0])]
    wp = wp.center(*at) if any(at) else wp
    if "circle" in shape:
        return wp.circle(ev(shape["circle"]["d"], p) / 2)
    if "rect" in shape:
        return wp.rect(ev(shape["rect"]["w"], p), ev(shape["rect"]["l"], p))
    if "ellipse" in shape:
        return wp.ellipse(ev(shape["ellipse"]["w"], p) / 2, ev(shape["ellipse"]["l"], p) / 2)
    if "polygon" in shape:
        return wp.polyline([(ev(x, p), ev(y, p)) for x, y in shape["polygon"]]).close()
    if "spline" in shape:
        pts = ring_order([(ev(x, p), ev(y, p)) for x, y in shape["spline"]])
        # Point k at parameter k/n, as Fusion lofts them. CadQuery's default spaces them by chord
        # length, so point k of one section met a different place on the next, the loft twisted,
        # and it came out 6% thinner than Fusion's.
        return wp.spline(pts, periodic=True, parameters=[k / len(pts) for k in range(len(pts) + 1)]).close()
    raise ValueError(f"unknown shape {list(shape)}")


def _loft(wires):
    """A smooth loft parametrised the way Fusion's comes out: OpenCascade's default (chord
    length) made the agent's five-ellipse mouse 3% fuller than Fusion builds it; isoparametric
    lands within 0.5%."""
    import cadquery as cq
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.Approx import Approx_IsoParametric
    b = BRepOffsetAPI_ThruSections(True, False, 1e-6)
    b.SetParType(Approx_IsoParametric)
    for w in wires:
        b.AddWire(w.wrapped)
    b.Build()
    return cq.Solid(b.Shape())


def ring_order(pts):
    """A closed outline's points anticlockwise, starting nearest the +X direction from their
    centre, so the sections of a loft line up instead of twisting. Shared with the Fusion script."""
    import math
    pts = [tuple(q) for q in pts]
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
    if area < 0:
        pts = pts[::-1]
    cx = sum(q[0] for q in pts) / len(pts); cy = sum(q[1] for q in pts) / len(pts)
    i = min(range(len(pts)), key=lambda k: abs(math.atan2(pts[k][1] - cy, pts[k][0] - cx)))
    return pts[i:] + pts[:i]


def _path_points(path, p):
    pts = [(ev(a, p), ev(b, p)) for a, b in path["points"]]
    return [(a, 0.0, b) for a, b in pts] if path.get("plane", "XZ") == "XZ" else [(0.0, a, b) for a, b in pts]


def to_cadquery(tree, p):
    """Build the tree; returns (cq.Shape, warnings). A fillet or chamfer that the kernel
    refuses is skipped with a warning rather than failing the whole model."""
    import cadquery as cq
    body, warns = None, []

    def combine(solid, mode):
        nonlocal body
        if body is None or mode == "new":
            body = solid if body is None else body.union(solid)
        elif mode == "cut":
            body = body.cut(solid)
        else:
            body = body.union(solid)

    for s in tree["steps"]:
        op, mode = s["op"], s.get("mode", "add")
        if op == "revolve":
            pts = [(max(0.0, ev(r, p)), ev(z, p)) for r, z in s["profile"]]
            solid = cq.Workplane("XZ").polyline(pts).close().revolve(360, (0, 0, 0), (0, 1, 0))
            combine(solid, mode)
        elif op == "extrude":
            wp = cq.Workplane("XY").workplane(offset=ev(s.get("from_z", 0), p))
            combine(_shape_cq(wp, s["shape"], p).extrude(ev(s["height"], p)), mode)
        elif op == "loft":
            # Each section on its own plane: chained, a section's "at" moved every one after it,
            # while Fusion moves only that section.
            secs = sorted(s["sections"], key=lambda q: ev(q["z"], p))
            wires = [_shape_cq(cq.Workplane("XY").workplane(offset=ev(q["z"], p)), q["shape"], p).val() for q in secs]
            solid = _loft(wires)
            # A smooth loft through uneven sections can swing far outside them; Fusion then
            # refuses it ("the loft would flow in an invalid direction"), so refuse it here too.
            lo = np.min([[w.BoundingBox().xmin, w.BoundingBox().ymin] for w in wires], axis=0)
            hi = np.max([[w.BoundingBox().xmax, w.BoundingBox().ymax] for w in wires], axis=0)
            bb = solid.BoundingBox()
            over = max(lo[0] - bb.xmin, lo[1] - bb.ymin, bb.xmax - hi[0], bb.ymax - hi[1])
            if over > max(2.0, 0.1 * float(np.max(hi - lo))):
                raise ValueError(f"loft {s.get('id')!r} swings {over:.0f} mm outside its sections: use 3 to 5 "
                                 "sections whose shapes change gradually")
            combine(cq.Workplane("XY").add(solid), mode)
        elif op == "sweep":
            pts = _path_points(s["path"], p)
            path = cq.Workplane("XY").spline(pts, includeCurrent=False) if len(pts) > 2 else cq.Workplane("XY").polyline(pts)
            t = cq.Vector(*pts[1]) - cq.Vector(*pts[0])
            xdir = cq.Vector(0, 1, 0) if s["path"].get("plane", "XZ") == "XZ" else cq.Vector(1, 0, 0)
            plane = cq.Plane(origin=cq.Vector(*pts[0]), xDir=xdir, normal=t.normalized())
            combine(_shape_cq(cq.Workplane(plane), s["section"], p).sweep(path, transition="round"), mode)
        elif op == "shell":
            try:
                th = ev(s["thickness"], p)
                body = body.faces(">Z").shell(-th) if s.get("open", "top") == "top" else body.shell(-th)
            except Exception as e:
                warns.append(f"{s.get('id')}: shell skipped ({type(e).__name__})")
        elif op in ("fillet", "chamfer"):
            sel = {"top": ">Z", "bottom": "<Z", "vertical": "|Z", "all": None}[s["edges"]]
            try:
                edges = body.edges(sel) if sel else body.edges()
                r = ev(s.get("radius", s.get("size", 1)), p)
                body = edges.fillet(r) if op == "fillet" else edges.chamfer(r)
            except Exception as e:
                warns.append(f"{s.get('id')}: {op} skipped ({type(e).__name__})")
    shape = body.val() if hasattr(body, "val") else body
    solids = shape.Solids()
    if len(solids) > 1:
        shape = solids[0].fuse(*solids[1:]).clean()
    return shape, warns


# --- Fusion 360 -------------------------------------------------------------------------------

FUSION_HEADER = '''"""{title}

A Fusion 360 script written by Bevell. In Fusion: Utilities > Add-Ins > Scripts and Add-Ins,
press + next to My Scripts, choose this script's folder, then Run. It opens a new design whose
timeline is the feature tree below and whose user parameters are its named dimensions, fitted
to {n_photos} calibrated photos. Change a parameter under Modify > Change Parameters.
"""
import adsk.core, adsk.fusion, math, traceback

PARAMETERS = {params}
STEPS = {steps}
'''

FUSION_BODY = r'''
FUNS = {"min": min, "max": max, "sqrt": math.sqrt, "abs": abs,
        "sin": lambda d: math.sin(math.radians(d)), "cos": lambda d: math.cos(math.radians(d)), "tan": lambda d: math.tan(math.radians(d))}


def mm(expr):
    """An expression in the parameters, in millimetres."""
    return float(eval(str(expr), {"__builtins__": {}}, {**FUNS, **{k: v[0] for k, v in PARAMETERS.items()}}))


def cm(expr):
    return mm(expr) / 10.0


def length(expr):
    """A Fusion value input that stays linked to the user parameters. The parameters are in mm
    and the design's units are mm, so bare numbers in an expression read as mm too."""
    return adsk.core.ValueInput.createByString(str(expr))


def P(x, y, z=0.0):
    return adsk.core.Point3D.create(x, y, z)


def ring_order(pts):
    """A closed outline's points anticlockwise, starting nearest the +X direction from their
    centre, so the sections of a loft line up instead of twisting. Shared with the Fusion script."""
    import math
    pts = [tuple(q) for q in pts]
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
    if area < 0:
        pts = pts[::-1]
    cx = sum(q[0] for q in pts) / len(pts); cy = sum(q[1] for q in pts) / len(pts)
    i = min(range(len(pts)), key=lambda k: abs(math.atan2(pts[k][1] - cy, pts[k][0] - cx)))
    return pts[i:] + pts[:i]


def run(context):
    app = adsk.core.Application.get()
    report = build(app.userInterface, close=False)
    if report.get("errors") or report.get("fatal"):
        app.userInterface.messageBox("Some steps did not build:\n\n" + "\n\n".join(report.get("errors", []) + [report.get("fatal", "")])[:1800])


def build(ui=None, close=False):
    """Build the tree in a new design and report on it. With ui None (BevellBridge), no dialogs."""
    report = {"errors": [], "timeline": [], "parameters": {}, "bodies": []}
    doc = None
    try:
        app = adsk.core.Application.get()
        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        design.fusionUnitsManager.distanceDisplayUnits = adsk.fusion.DistanceUnits.MillimeterDistanceUnits
        root = design.rootComponent
        for name, (value, what) in PARAMETERS.items():
            design.userParameters.add(name, adsk.core.ValueInput.createByString(f"{value} mm"), "mm", what)
        F, OP = root.features, adsk.fusion.FeatureOperations
        body = None

        def operation(mode):
            if body is None or mode == "new":
                return OP.NewBodyFeatureOperation
            return OP.CutFeatureOperation if mode == "cut" else OP.JoinFeatureOperation

        def plane_at(z_expr, name):
            if abs(mm(z_expr)) < 1e-9:
                return root.xYConstructionPlane
            pi = root.constructionPlanes.createInput()
            pi.setByOffset(root.xYConstructionPlane, length(z_expr))
            pl = root.constructionPlanes.add(pi); pl.name = name + " plane"
            return pl

        def draw(sketch, shape, origin=(0.0, 0.0)):
            at = shape.get("at", [0, 0]); cx, cy = origin[0] + cm(at[0]), origin[1] + cm(at[1])
            if "circle" in shape:
                c = sketch.sketchCurves.sketchCircles.addByCenterRadius(P(cx, cy), cm(shape["circle"]["d"]) / 2)
                try:
                    d = sketch.sketchDimensions.addDiameterDimension(c, P(cx + cm(shape["circle"]["d"]), cy))
                    d.parameter.expression = str(shape["circle"]["d"])
                except Exception:
                    pass
            elif "rect" in shape:
                w, l = cm(shape["rect"]["w"]), cm(shape["rect"]["l"])
                sketch.sketchCurves.sketchLines.addCenterPointRectangle(P(cx, cy), P(cx + w / 2, cy + l / 2))
            elif "ellipse" in shape:
                w, l = cm(shape["ellipse"]["w"]), cm(shape["ellipse"]["l"])
                sketch.sketchCurves.sketchEllipses.add(P(cx, cy), P(cx + w / 2, cy), P(cx, cy + l / 2))
            elif "polygon" in shape:
                pts = [P(cx + cm(x), cy + cm(y)) for x, y in shape["polygon"]]
                for a, b in zip(pts, pts[1:] + pts[:1]):
                    sketch.sketchCurves.sketchLines.addByTwoPoints(a, b)
            elif "spline" in shape:
                pts = adsk.core.ObjectCollection.create()
                for x, y in ring_order([(cm(x), cm(y)) for x, y in shape["spline"]]):
                    pts.add(P(cx + x, cy + y))
                sketch.sketchCurves.sketchFittedSplines.add(pts).isClosed = True

        def edges_of(kind):
            b = root.bRepBodies.item(0)
            zs = [b.boundingBox.minPoint.z, b.boundingBox.maxPoint.z]
            out = adsk.core.ObjectCollection.create()
            for e in b.edges:
                p0, p1 = e.startVertex.geometry if e.startVertex else None, e.endVertex.geometry if e.endVertex else None
                bb = e.boundingBox
                if kind == "all":
                    out.add(e)
                elif kind == "top" and abs(bb.minPoint.z - zs[1]) < 1e-3:
                    out.add(e)
                elif kind == "bottom" and abs(bb.maxPoint.z - zs[0]) < 1e-3:
                    out.add(e)
                elif kind == "vertical" and abs(bb.maxPoint.x - bb.minPoint.x) < 1e-4 and abs(bb.maxPoint.y - bb.minPoint.y) < 1e-4:
                    out.add(e)
            return out

        for s in STEPS:
            op, mode = s["op"], s.get("mode", "add")
            try:
                if op == "revolve":
                    sk = root.sketches.add(root.xZConstructionPlane); sk.name = s.get("id", "revolve") + " profile"
                    # On the XZ plane, sketch x is world X and sketch y is world -Z.
                    pts = [P(max(0.0, cm(r)), -cm(z)) for r, z in s["profile"]]
                    axis = None
                    for a, b in zip(pts, pts[1:] + pts[:1]):
                        if a.distanceTo(b) > 1e-6:
                            line = sk.sketchCurves.sketchLines.addByTwoPoints(a, b)
                            if abs(a.x) < 1e-6 and abs(b.x) < 1e-6:
                                axis = line          # the profile's own edge on the axis
                    if axis is None:
                        zmax = max(cm(z) for _, z in s["profile"])
                        axis = sk.sketchCurves.sketchLines.addByTwoPoints(P(0, 0), P(0, -max(zmax, 0.1))); axis.isConstruction = True
                    ri = F.revolveFeatures.createInput(sk.profiles.item(0), axis, operation(mode))
                    ri.setAngleExtent(False, adsk.core.ValueInput.createByString("360 deg"))
                    F.revolveFeatures.add(ri).name = s.get("id", "revolve")
                elif op == "extrude":
                    sk = root.sketches.add(plane_at(s.get("from_z", 0), s.get("id", "extrude"))); sk.name = s.get("id", "extrude") + " sketch"
                    draw(sk, s["shape"])
                    prof = adsk.core.ObjectCollection.create()
                    for i in range(sk.profiles.count):
                        prof.add(sk.profiles.item(i))
                    ei = F.extrudeFeatures.createInput(prof, operation(mode))
                    ei.setDistanceExtent(False, length(s["height"]))
                    F.extrudeFeatures.add(ei).name = s.get("id", "extrude")
                elif op == "loft":
                    li = F.loftFeatures.createInput(operation(mode))
                    for k, sec in enumerate(sorted(s["sections"], key=lambda q: mm(q["z"]))):
                        sk = root.sketches.add(plane_at(sec["z"], f"{s.get('id', 'loft')} section {k + 1}")); sk.name = f"{s.get('id', 'loft')} section {k + 1}"
                        draw(sk, sec["shape"])
                        li.loftSections.add(sk.profiles.item(0))
                    F.loftFeatures.add(li).name = s.get("id", "loft")
                elif op == "sweep":
                    xz = s["path"].get("plane", "XZ") == "XZ"
                    sk = root.sketches.add(root.xZConstructionPlane if xz else root.yZConstructionPlane); sk.name = s.get("id", "sweep") + " path"
                    # XZ: sketch (x, -z); YZ: sketch (-z, y).
                    world = [(cm(a), 0.0, cm(b)) if xz else (0.0, cm(a), cm(b)) for a, b in s["path"]["points"]]
                    spts = adsk.core.ObjectCollection.create()
                    for x, y, z in world:
                        spts.add(P(x, -z) if xz else P(-z, y))
                    curve = sk.sketchCurves.sketchFittedSplines.add(spts) if len(world) > 2 else sk.sketchCurves.sketchLines.addByTwoPoints(spts.item(0), spts.item(1))
                    path = F.createPath(curve)
                    pi = root.constructionPlanes.createInput(); pi.setByDistanceOnPath(path, adsk.core.ValueInput.createByReal(0))
                    spl = root.constructionPlanes.add(pi); spl.name = s.get("id", "sweep") + " section plane"
                    psk = root.sketches.add(spl); psk.name = s.get("id", "sweep") + " section"
                    o = psk.modelToSketchSpace(P(*world[0]))
                    draw(psk, s["section"], (o.x, o.y))
                    si = F.sweepFeatures.createInput(psk.profiles.item(0), path, operation(mode))
                    F.sweepFeatures.add(si).name = s.get("id", "sweep")
                elif op == "shell":
                    b = root.bRepBodies.item(0)
                    faces = adsk.core.ObjectCollection.create()
                    if s.get("open", "top") == "top":
                        top = max((f for f in b.faces if f.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType),
                                  key=lambda f: f.centroid.z, default=None)
                        if top:
                            faces.add(top)
                    else:
                        faces.add(b)
                    shi = F.shellFeatures.createInput(faces, False)
                    shi.insideThickness = length(s["thickness"])
                    F.shellFeatures.add(shi).name = s.get("id", "shell")
                elif op in ("fillet", "chamfer"):
                    edges = edges_of(s["edges"])
                    size = s.get("radius", s.get("size", 1))
                    if op == "fillet":
                        fi = F.filletFeatures.createInput()
                        try:
                            fi.edgeSetInputs.addConstantRadiusEdgeSet(edges, length(size), True)
                        except AttributeError:
                            fi.addConstantRadiusEdgeSet(edges, length(size), True)
                        F.filletFeatures.add(fi).name = s.get("id", "fillet")
                    else:
                        ci = F.chamferFeatures.createInput2()
                        ci.chamferEdgeSets.addEqualDistanceChamferEdgeSet(edges, length(size), True)
                        F.chamferFeatures.add(ci).name = s.get("id", "chamfer")
                body = root.bRepBodies.item(0) if root.bRepBodies.count else None
            except Exception:
                report["errors"].append(f"step {s.get('id', op)} ({op}): {traceback.format_exc()[-700:]}")
        app.activeViewport.fit()
        report["timeline"] = [design.timeline.item(i).name for i in range(design.timeline.count)]
        report["parameters"] = {p.name: round(p.value * 10, 3) for p in design.userParameters}
        for b in root.bRepBodies:
            bb = b.boundingBox
            report["bodies"].append({"name": b.name, "volume_mm3": round(b.physicalProperties.volume * 1000, 1),
                                     "size_mm": [round((bb.maxPoint.x - bb.minPoint.x) * 10, 2), round((bb.maxPoint.y - bb.minPoint.y) * 10, 2),
                                                 round((bb.maxPoint.z - bb.minPoint.z) * 10, 2)], "solid": b.isSolid})
    except Exception:
        report["fatal"] = traceback.format_exc()[-1500:]
    if close and doc:
        try:
            doc.close(False)
        except Exception:
            pass
    return report
'''


# Fusion refuses a user parameter named like a unit ("param name is not valid": the block's
# l, b, t and r on 3 Nov), so short names and unit names get "_mm" in the Fusion script only.
FUSION_UNIT_NAMES = {"mm", "cm", "m", "km", "um", "nm", "in", "inch", "ft", "foot", "yd", "mi", "mil",
                     "deg", "rad", "l", "ml", "g", "kg", "lb", "oz", "s", "min", "hr", "t"}
_NOT_EXPRESSIONS = {"op", "id", "mode", "edges", "plane", "open"}


def _fusion_names(tree):
    names = [q["name"] for q in tree["parameters"]]
    out = {}
    for n in names:
        if len(n) <= 2 or n.lower() in FUSION_UNIT_NAMES:
            new = n + "_mm"
            while new in names or new in out.values():
                new += "_"
            out[n] = new
    return out


def _renamed(obj, names, key=None):
    """`obj` with every parameter in `names` renamed inside its expressions."""
    import re
    if isinstance(obj, dict):
        return {k: _renamed(v, names, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_renamed(v, names, key) for v in obj]
    if isinstance(obj, str) and key not in _NOT_EXPRESSIONS and names:
        return re.sub(r"(?<![A-Za-z0-9_])(" + "|".join(map(re.escape, sorted(names, key=len, reverse=True))) + r")(?![A-Za-z0-9_])",
                      lambda m: names[m.group(1)], obj)
    return obj


def to_fusion_script(tree, params, title="Bevell model", n_photos=16):
    names = _fusion_names(tree)
    pars = {names.get(q["name"], q["name"]): [round(float(params.get(q["name"], q["value"])), 3), q.get("what", "")] for q in tree["parameters"]}
    return (FUSION_HEADER.format(title=title, n_photos=n_photos, params=json.dumps(pars, indent=4),
                                 steps=json.dumps(_renamed(tree["steps"], names), indent=1)) + FUSION_BODY)


def write_fusion_zip(out_dir, tree, title, n_photos=16):
    """The Fusion script folder and agent_fusion.zip that the web app offers, from a tree."""
    import os, shutil
    params = {q["name"]: q["value"] for q in tree["parameters"]}
    write_fusion_script(os.path.join(out_dir, "fusion", "BevellModel"), tree, params, title, n_photos)
    return shutil.make_archive(os.path.join(out_dir, "agent_fusion"), "zip", os.path.join(out_dir, "fusion"))


def write_fusion_script(folder, tree, params, title, n_photos=16):
    """Fusion runs a script from a folder named like the script, with a .manifest beside it."""
    import os
    os.makedirs(folder, exist_ok=True)
    name = os.path.basename(folder.rstrip("/"))
    open(os.path.join(folder, name + ".py"), "w").write(to_fusion_script(tree, params, title, n_photos))
    json.dump({"autodeskProduct": "Fusion360", "type": "script", "author": "Bevell", "description": {"": title},
               "supportedOS": "windows|mac", "editEnabled": True}, open(os.path.join(folder, name + ".manifest"), "w"), indent=1)
    return os.path.join(folder, name + ".py")
