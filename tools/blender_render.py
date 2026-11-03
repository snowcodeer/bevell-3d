"""Studio render of STL parts with Blender, for the demo. Still or turntable.

    blender -b -P tools/blender_render.py -- --out out/holder.png \
        --part out/airpods/holder.stl:dcdce0 --part out/airpods/model.stl:395af6
    blender -b -P tools/blender_render.py -- --turntable 120 --out out/turn/ --part ...
"""
import argparse, math, os, sys
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--part", action="append", required=True, help="path.stl:rrggbb")
ap.add_argument("--res", default="1600x1000")
ap.add_argument("--turntable", type=int, default=0, help="frames for a full turn")
ap.add_argument("--elevation", type=float, default=32.0)
ap.add_argument("--samples", type=int, default=64)
a = ap.parse_args(argv)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
w, h = (int(v) for v in a.res.split("x"))
scene.render.resolution_x, scene.render.resolution_y = w, h
scene.render.film_transparent = False
for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES"):
    try:
        scene.render.engine = engine
        break
    except TypeError:
        continue
if scene.render.engine == "CYCLES":
    scene.cycles.samples = a.samples
else:
    try:
        scene.eevee.taa_render_samples = a.samples
        scene.eevee.use_shadows = True
    except AttributeError:
        pass
scene.view_settings.exposure = -0.3
scene.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in scene.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"

world = bpy.data.worlds.new("World"); scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.93, 0.94, 0.96, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.25


def material(hexcol, rough=0.45):
    r, g, b = (int(hexcol[i:i + 2], 16) / 255 for i in (0, 2, 4))
    srgb = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    m = bpy.data.materials.new(hexcol); m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (srgb(r), srgb(g), srgb(b), 1)
    bsdf.inputs["Roughness"].default_value = rough
    return m


pivot = bpy.data.objects.new("pivot", None); scene.collection.objects.link(pivot)
objs = []
for spec in a.part:
    path, col = spec.rsplit(":", 1)
    bpy.ops.wm.stl_import(filepath=os.path.abspath(path), global_scale=0.001)   # mm -> m
    o = bpy.context.selected_objects[0]
    o.data.materials.append(material(col))
    for p in o.data.polygons:
        p.use_smooth = True
    o.parent = pivot
    objs.append(o)

pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
centre = (lo + hi) / 2
for o in objs:                                   # centre the parts on the pivot
    o.location -= Vector((centre.x, centre.y, lo.z))
size = max(hi - lo)

bpy.ops.mesh.primitive_plane_add(size=size * 40, location=(0, 0, 0))
floor = bpy.context.active_object
floor.data.materials.append(material("f2f3f6", 0.8))

cam_data = bpy.data.cameras.new("cam"); cam_data.lens = 70
cam = bpy.data.objects.new("cam", cam_data); scene.collection.objects.link(cam); scene.camera = cam
dist = size * 5.2
el = math.radians(a.elevation)
cam.location = (dist * math.cos(el) * math.cos(math.radians(-55)), dist * math.cos(el) * math.sin(math.radians(-55)), dist * math.sin(el) + (hi.z - lo.z) * 0.3)
target = Vector((0, 0, (hi.z - lo.z) * 0.35))
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()

for name, loc, energy, sz in [("key", (-1.2, -1.6, 2.2), 5, 1.2), ("fill", (1.8, -0.6, 1.2), 1.5, 1.5), ("rim", (0.4, 2.0, 1.8), 3, 1.0)]:
    ld = bpy.data.lights.new(name, "AREA"); ld.energy = energy * (size / 0.06) ** 2; ld.size = size * sz
    lo_ = bpy.data.objects.new(name, ld); scene.collection.objects.link(lo_)
    lo_.location = Vector(loc) * size * 1.6
    lo_.rotation_euler = (Vector((0, 0, 0)) - lo_.location).to_track_quat("-Z", "Y").to_euler()

if a.turntable:
    os.makedirs(a.out, exist_ok=True)
    for f in range(a.turntable):
        pivot.rotation_euler = (0, 0, 2 * math.pi * f / a.turntable)
        scene.render.filepath = os.path.join(a.out, f"frame_{f:04d}.png")
        bpy.ops.render.render(write_still=True)
else:
    scene.render.filepath = os.path.abspath(a.out)
    bpy.ops.render.render(write_still=True)
print("rendered", a.out, "with", scene.render.engine)
