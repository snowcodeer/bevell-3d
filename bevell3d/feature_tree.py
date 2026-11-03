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
    raise ValueError(f"unknown shape {list(shape)}")


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
            secs = sorted(s["sections"], key=lambda q: ev(q["z"], p))
            wp = cq.Workplane("XY").workplane(offset=ev(secs[0]["z"], p))
            wp = _shape_cq(wp, secs[0]["shape"], p)
            z = ev(secs[0]["z"], p)
            for sec in secs[1:]:
                z2 = ev(sec["z"], p)
                wp = _shape_cq(wp.workplane(offset=z2 - z), sec["shape"], p); z = z2
            combine(wp.loft(combine=True), mode)
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
    """A Fusion value input that stays linked to the user parameters."""
    return adsk.core.ValueInput.createByString(f"({expr}) * 1 mm")


def P(x, y, z=0.0):
    return adsk.core.Point3D.create(x, y, z)


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get(); ui = app.userInterface
        app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
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

        def plane_at(z_expr):
            if abs(mm(z_expr)) < 1e-9:
                return root.xYConstructionPlane
            pi = root.constructionPlanes.createInput()
            pi.setByOffset(root.xYConstructionPlane, length(z_expr))
            return root.constructionPlanes.add(pi)

        def draw(sketch, shape, origin=(0.0, 0.0)):
            at = shape.get("at", [0, 0]); cx, cy = origin[0] + cm(at[0]), origin[1] + cm(at[1])
            if "circle" in shape:
                c = sketch.sketchCurves.sketchCircles.addByCenterRadius(P(cx, cy), cm(shape["circle"]["d"]) / 2)
                try:
                    d = sketch.sketchDimensions.addDiameterDimension(c, P(cx + cm(shape["circle"]["d"]), cy))
                    d.parameter.expression = f"({shape['circle']['d']}) * 1 mm"
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
                    sk = root.sketches.add(root.xZConstructionPlane); sk.name = s.get("id", "profile")
                    # On the XZ plane, sketch x is world X and sketch y is world -Z.
                    pts = [P(max(0.0, cm(r)), -cm(z)) for r, z in s["profile"]]
                    for a, b in zip(pts, pts[1:] + pts[:1]):
                        if a.distanceTo(b) > 1e-6:
                            sk.sketchCurves.sketchLines.addByTwoPoints(a, b)
                    zmax = max(cm(z) for _, z in s["profile"])
                    axis = sk.sketchCurves.sketchLines.addByTwoPoints(P(0, 0), P(0, -max(zmax, 0.1))); axis.isConstruction = True
                    ri = F.revolveFeatures.createInput(sk.profiles.item(0), axis, operation(mode))
                    ri.setAngleExtent(False, adsk.core.ValueInput.createByString("360 deg"))
                    F.revolveFeatures.add(ri).name = s.get("id", "revolve")
                elif op == "extrude":
                    sk = root.sketches.add(plane_at(s.get("from_z", 0))); sk.name = s.get("id", "sketch")
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
                        sk = root.sketches.add(plane_at(sec["z"])); sk.name = f"{s.get('id', 'loft')}_{k}"
                        draw(sk, sec["shape"])
                        li.loftSections.add(sk.profiles.item(0))
                    F.loftFeatures.add(li).name = s.get("id", "loft")
                elif op == "sweep":
                    xz = s["path"].get("plane", "XZ") == "XZ"
                    sk = root.sketches.add(root.xZConstructionPlane if xz else root.yZConstructionPlane); sk.name = s.get("id", "path")
                    # XZ: sketch (x, -z); YZ: sketch (-z, y).
                    world = [(cm(a), 0.0, cm(b)) if xz else (0.0, cm(a), cm(b)) for a, b in s["path"]["points"]]
                    spts = adsk.core.ObjectCollection.create()
                    for x, y, z in world:
                        spts.add(P(x, -z) if xz else P(-z, y))
                    curve = sk.sketchCurves.sketchFittedSplines.add(spts) if len(world) > 2 else sk.sketchCurves.sketchLines.addByTwoPoints(spts.item(0), spts.item(1))
                    path = F.createPath(curve)
                    pi = root.constructionPlanes.createInput(); pi.setByDistanceOnPath(path, adsk.core.ValueInput.createByReal(0))
                    psk = root.sketches.add(root.constructionPlanes.add(pi)); psk.name = s.get("id", "section") + "_section"
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
                ui.messageBox(f"Step {s.get('id', op)} ({op}) did not build and was skipped:\n{traceback.format_exc()[-600:]}")
        app.activeViewport.fit()
    except Exception:
        if ui:
            ui.messageBox("Bevell script failed:\n" + traceback.format_exc())
'''


def to_fusion_script(tree, params, title="Bevell model", n_photos=16):
    pars = {q["name"]: [round(float(params.get(q["name"], q["value"])), 3), q.get("what", "")] for q in tree["parameters"]}
    return (FUSION_HEADER.format(title=title, n_photos=n_photos, params=json.dumps(pars, indent=4),
                                 steps=json.dumps(tree["steps"], indent=1)) + FUSION_BODY)


def write_fusion_script(folder, tree, params, title, n_photos=16):
    """Fusion runs a script from a folder named like the script, with a .manifest beside it."""
    import os
    os.makedirs(folder, exist_ok=True)
    name = os.path.basename(folder.rstrip("/"))
    open(os.path.join(folder, name + ".py"), "w").write(to_fusion_script(tree, params, title, n_photos))
    json.dump({"autodeskProduct": "Fusion360", "type": "script", "author": "Bevell", "description": {"": title},
               "supportedOS": "windows|mac", "editEnabled": True}, open(os.path.join(folder, name + ".manifest"), "w"), indent=1)
    return os.path.join(folder, name + ".py")
