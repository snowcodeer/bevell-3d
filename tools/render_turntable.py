"""A turntable of one or more meshes, for the demo video's B-roll.

    blender -b -P tools/render_turntable.py -- --out out/broll/servo \
        --item model_cad.stl:0.80,0.80,0.82:-35 --item agent_model.stl:0.22,0.35,0.96:35 [--tag <scan dir>]

Each --item is path:r,g,b:x-offset-mm. Items are centred on their own footprint, then moved
along x, so a scan and its CAD stand side by side. --tag adds the fixture's printed tag from
<dir>/fixture.json and <dir>/tag_texture.png, in the frame of the first item (render it with
the fixture as the first item and the part second, shifted by the part's seat). Writes PNG
frames to --out; tools/make_broll.sh turns them into an H.264 MP4.
"""
import argparse, json, math, os, sys
import bpy
import numpy as np
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--item", action="append", required=True)
ap.add_argument("--tag")
ap.add_argument("--frames", type=int, default=150)
ap.add_argument("--only", type=int, help="render just this frame (a look before the whole turn)")
ap.add_argument("--res", default="1920x1080")
ap.add_argument("--elev", type=float, default=24.0)
ap.add_argument("--keep-frame", action="store_true", help="keep the items' shared frame instead of centring each")
a = ap.parse_args(argv)
W, H = (int(v) for v in a.res.split("x"))

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.film_transparent = False
scene.view_settings.view_transform = "Standard"
scene.render.image_settings.file_format = "PNG"
world = bpy.data.worlds.new("w"); scene.world = world; world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.075, 0.08, 0.09, 1)   # near-black ground
world.node_tree.nodes["Background"].inputs[1].default_value = 0.3


def material(name, rgb=None, image=None, rough=0.45):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]; b.inputs["Roughness"].default_value = rough
    if image:
        t = m.node_tree.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(image); t.interpolation = "Closest"
        m.node_tree.links.new(t.outputs["Color"], b.inputs["Base Color"])
    else:
        b.inputs["Base Color"].default_value = (*rgb, 1)
    return m


objs, offsets = [], []
for spec in a.item:
    path, rgb, dx = spec.rsplit(":", 2)
    bpy.ops.wm.stl_import(filepath=path)
    o = bpy.context.selected_objects[0]
    o.scale = (0.001, 0.001, 0.001)
    o.data.materials.append(material(os.path.basename(path), tuple(float(v) for v in rgb.split(","))))
    objs.append(o); offsets.append(float(dx) / 1000)
bpy.context.view_layer.update()
pts_of = [np.array([o.matrix_world @ v.co for v in o.data.vertices]) for o in objs]
if a.keep_frame:                       # one shift for all: they keep their places relative to each other
    allp = np.vstack(pts_of); c = (allp.min(0) + allp.max(0)) / 2
    shifts = [Vector((-c[0] + dx, -c[1], -allp.min(0)[2])) for dx in offsets]
else:                                  # each on its own footprint, then side by side
    shifts = [Vector((-(p.min(0)[0] + p.max(0)[0]) / 2 + dx, -(p.min(0)[1] + p.max(0)[1]) / 2, -p.min(0)[2])) for p, dx in zip(pts_of, offsets)]
for o, sh in zip(objs, shifts):
    o.location = sh
first_shift = shifts[0]

if a.tag:
    rep = json.load(open(os.path.join(a.tag, "fixture.json")))
    t = rep["tag_in_holder"]
    o_mm = np.array(t["origin_mm"]); x, y, z = (np.array(t[k]) for k in ("x_axis", "y_axis", "z_axis"))
    bpy.ops.mesh.primitive_plane_add(size=rep["tag"]["size_mm"] / 1000)
    tag = bpy.context.object
    R = Matrix([list(x), list(y), list(z)]).transposed()
    tag.matrix_world = Matrix.Translation(Vector((o_mm + z * 0.05) / 1000) + first_shift) @ R.to_4x4()
    tag.data.materials.append(material("tag", image=os.path.join(a.tag, "tag_texture.png"), rough=0.9))

# A floor that catches the light, and three area lights.
bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0, 0, -0.0003))
bpy.context.object.data.materials.append(material("floor", (0.11, 0.115, 0.13), rough=0.7))
for nm, loc, e in (("key", (-0.25, -0.3, 0.45), 6), ("fill", (0.35, -0.1, 0.25), 2), ("rim", (0.0, 0.4, 0.3), 3.5)):
    ld = bpy.data.lights.new(nm, "AREA"); ld.energy = e; ld.size = 0.4
    lo = bpy.data.objects.new(nm, ld); scene.collection.objects.link(lo); lo.location = loc
    lo.rotation_euler = (Vector((0, 0, 0.02)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()

# The camera orbits the middle of everything once, at a distance that keeps it all in frame.
bpy.context.view_layer.update()
allp = np.vstack([[o.matrix_world @ v.co for v in o.data.vertices] for o in objs])
lo, hi = allp.min(0), allp.max(0)
target = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (hi[2] - lo[2]) * 0.4))
radius = float(np.linalg.norm(hi - lo)) / 2
cd = bpy.data.cameras.new("cam"); cd.lens = 50.0; cd.sensor_width = 36.0
cam = bpy.data.objects.new("cam", cd); scene.collection.objects.link(cam); scene.camera = cam
fov = 2 * math.atan(cd.sensor_width / 2 / cd.lens) * min(1.0, H / W)
dist = radius / math.sin(fov / 2) * 0.8
el = math.radians(a.elev)
os.makedirs(a.out, exist_ok=True)
for k in ([a.only] if a.only is not None else range(a.frames)):
    az = 2 * math.pi * k / a.frames - math.pi / 2
    cam.location = target + dist * Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.join(os.path.abspath(a.out), f"f{k:04d}.png")
    bpy.ops.render.render(write_still=True)
print("rendered", a.frames, "frames to", a.out)
