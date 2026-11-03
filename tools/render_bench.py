"""Photograph a scanned object on the capture sheet in Blender, from known cameras.

World frame as in bevell3d.sheet, in metres here: X along the sheet's long edge, Y towards
its top edge, Z up, the sheet's printed top-left at (0, 0.210).

    blender -b -P tools/render_bench.py -- --obj model.obj --out out/bench/mug \
        --x 148 --y 105 --yaw 30
"""
import argparse, json, math, os, sys
import bpy
from mathutils import Vector, Euler

argv = sys.argv[sys.argv.index("--") + 1:]
ap = argparse.ArgumentParser()
ap.add_argument("--obj", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--sheet", default=os.path.join(os.path.dirname(__file__), "..", "out", "bench", "sheet_20ppm.png"))
ap.add_argument("--x", type=float, default=148.5)
ap.add_argument("--y", type=float, default=105.0)
ap.add_argument("--yaw", type=float, default=0.0)
ap.add_argument("--res", default="2016x1512")
ap.add_argument("--samples", type=int, default=24)
a = ap.parse_args(argv)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
W, H = (int(v) for v in a.res.split("x"))
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.engine = "BLENDER_EEVEE"
scene.eevee.taa_render_samples = a.samples
scene.render.image_settings.file_format = "JPEG"
scene.render.image_settings.quality = 92
scene.view_settings.view_transform = "Standard"

world = bpy.data.worlds.new("World"); scene.world = world; world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.8, 0.82, 0.85, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.25


def principled(name, colour=None, image=None, rough=0.6):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = rough
    if image:
        tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = bpy.data.images.load(image)
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    elif colour:
        bsdf.inputs["Base Color"].default_value = (*colour, 1)
    return m


# Table: a warm wood-like grey, far bigger than the sheet.
bpy.ops.mesh.primitive_plane_add(size=3.0, location=(0.15, 0.1, -0.0004))
bpy.context.active_object.data.materials.append(principled("table", (0.32, 0.22, 0.14), rough=0.5))

# The capture sheet at true size, its image's top row along the sheet's top edge.
bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.1485, 0.105, 0.0))
sheet = bpy.context.active_object
sheet.scale = (0.297, 0.210, 1.0)
sheet.data.materials.append(principled("sheet", image=os.path.abspath(a.sheet), rough=0.9))

# The object: GSO meshes are Z-up metres with their base at z = 0.
bpy.ops.wm.obj_import(filepath=os.path.abspath(a.obj), forward_axis="Y", up_axis="Z")
obj = bpy.context.selected_objects[0]
# GSO keeps its texture in ../materials/textures/, where the OBJ importer does not look.
tex = os.path.join(os.path.dirname(os.path.abspath(a.obj)), "..", "materials", "textures", "texture.png")
if os.path.exists(tex):
    mat = principled("object", image=tex, rough=0.5)
    obj.data.materials.clear(); obj.data.materials.append(mat)
obj.rotation_euler = Euler((0, 0, math.radians(a.yaw)))
obj.location = (a.x / 1000, a.y / 1000, 0.0)
bpy.context.view_layer.update()
pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
top = max(p.z for p in pts)
target = Vector((a.x / 1000, a.y / 1000, top * 0.4))

for name, loc, energy, size in [("key", (-0.25, -0.35, 0.6), 9, 0.4), ("fill", (0.5, 0.0, 0.35), 3, 0.6)]:
    ld = bpy.data.lights.new(name, "AREA"); ld.energy = energy; ld.size = size
    lo = bpy.data.objects.new(name, ld); scene.collection.objects.link(lo)
    lo.location = Vector(loc) + Vector((0.15, 0.1, 0))
    lo.rotation_euler = (Vector((0.15, 0.1, 0)) - lo.location).to_track_quat("-Z", "Y").to_euler()

cd = bpy.data.cameras.new("cam"); cd.sensor_fit = "HORIZONTAL"; cd.sensor_width = 36.0; cd.lens = 26.0
cam = bpy.data.objects.new("cam", cd); scene.collection.objects.link(cam); scene.camera = cam

# The capture guide: a ring at 45 degrees, a ring at 10 degrees, two from above.
shots = [(45, az, 0.33) for az in range(0, 360, 60)] + [(10, az, 0.31) for az in range(15, 360, 45)] + \
        [(80, 90, 0.34), (80, 270, 0.34)]
os.makedirs(os.path.join(a.out, "photos"), exist_ok=True)
cams = []
for k, (el, az, dist) in enumerate(shots):
    e, z = math.radians(el), math.radians(az)
    cam.location = target + dist * Vector((math.cos(e) * math.cos(z), math.cos(e) * math.sin(z), math.sin(e)))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.abspath(os.path.join(a.out, "photos", f"IMG_{k:02d}.jpg"))
    bpy.ops.render.render(write_still=True)
    cams.append({"name": f"IMG_{k:02d}", "elevation": el, "azimuth": az, "location_mm": [c * 1000 for c in cam.location]})

json.dump({"obj": os.path.abspath(a.obj), "x_mm": a.x, "y_mm": a.y, "yaw_deg": a.yaw,
           "focal_px": W * 26.0 / 36.0, "size": [W, H], "cameras": cams},
          open(os.path.join(a.out, "truth.json"), "w"), indent=1)
print("rendered", len(shots), "photos to", a.out)
