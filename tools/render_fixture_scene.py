"""Render a robot's view of a fixture: the part seated, the tag in its recess, from a known camera.

    blender -b -P tools/render_fixture_scene.py -- --dir <scan result dir> --out scene.png

Needs fixture.stl, fixture.json, model.stl and tag_texture.png (the bare marker, from
cv2.aruco.generateImageMarker) in --dir. Writes the render and camera.json, the
camera's true intrinsics and world-to-camera pose in OpenCV's convention, so a test can check
tools/pick_preview.py against the truth, and the image serves the demo.
"""
import argparse, json, math, os, sys
import bpy, numpy as np
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--res", default="1600x1200"); ap.add_argument("--elev", type=float, default=50.0)
ap.add_argument("--azim", type=float, help="degrees round; by default from behind the tag, looking at the part"); ap.add_argument("--dist", type=float, default=0.32)
a = ap.parse_args(argv)
W, H = (int(v) for v in a.res.split("x"))
rep = json.load(open(os.path.join(a.dir, "fixture.json")))

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"; scene.render.resolution_x, scene.render.resolution_y = W, H
scene.view_settings.view_transform = "Standard"
world = bpy.data.worlds.new("w"); scene.world = world; world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.8, 0.82, 0.85, 1); world.node_tree.nodes["Background"].inputs[1].default_value = 0.25


def mat(name, colour=None, image=None, rough=0.5):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]; b.inputs["Roughness"].default_value = rough
    if image:
        t = m.node_tree.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(image); t.interpolation = "Closest"
        m.node_tree.links.new(t.outputs["Color"], b.inputs["Base Color"])
    else:
        b.inputs["Base Color"].default_value = (*colour, 1)
    return m


def load(path, colour, shift=(0, 0, 0)):
    bpy.ops.wm.stl_import(filepath=path)
    o = bpy.context.selected_objects[0]
    o.scale = (0.001, 0.001, 0.001); o.location = tuple(v / 1000 for v in shift)
    o.data.materials.append(mat(os.path.basename(path), colour))
    return o


load(os.path.join(a.dir, "fixture.stl"), (0.92, 0.92, 0.94))
load(os.path.join(a.dir, "model.stl"), (0.85, 0.35, 0.2), rep["part"]["seat_shift_mm"])
# The table.
bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.15, 0.1, -0.0002))
bpy.context.object.data.materials.append(mat("table", (0.32, 0.28, 0.24), rough=0.8))

# The tag: its image on a 30 mm plane, the marker's x and y on the plane's, top edge (+y) towards the part.
# Blender's Python has no OpenCV, so the marker image is made beforehand (tag_texture.png).
size = rep["tag"]["size_mm"]
tag_png = os.path.join(a.dir, "tag_texture.png")
t = rep["tag_in_holder"]
o_mm = np.array(t["origin_mm"]); x, y, z = (np.array(t[k]) for k in ("x_axis", "y_axis", "z_axis"))
bpy.ops.mesh.primitive_plane_add(size=size / 1000)
tag = bpy.context.object
R = Matrix([list(x), list(y), list(z)]).transposed()       # columns: the tag's axes in the world
tag.matrix_world = Matrix.Translation(Vector((o_mm + z * 0.05) / 1000)) @ R.to_4x4()
tag.data.materials.append(mat("tag", image=tag_png, rough=0.9))

# Light and camera: looking at the part from `azim` round and `elev` up, `dist` metres away.
target = Vector((o_mm + np.array(t["y_axis"]) * 45) / 1000) + Vector((0, 0, 0.01))
# From behind the tag by default, 25 degrees off its axis: the holder's wall hides a low tag
# from a camera on the far side, as a robot's camera there would find too.
behind = -np.array(t["y_axis"])
az = math.radians(a.azim) if a.azim is not None else math.atan2(behind[1], behind[0]) + math.radians(25)
el = math.radians(a.elev)
cam_loc = target + a.dist * Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)))
cd = bpy.data.cameras.new("cam"); cd.lens = 28.0; cd.sensor_width = 36.0; cd.sensor_fit = "HORIZONTAL"
cam = bpy.data.objects.new("cam", cd); scene.collection.objects.link(cam); scene.camera = cam
cam.location = cam_loc; cam.rotation_euler = (target - cam_loc).to_track_quat("-Z", "Y").to_euler()
for nm, loc, e in (("key", (0.0, -0.3, 0.6), 9), ("fill", (0.45, 0.35, 0.4), 3)):
    ld = bpy.data.lights.new(nm, "AREA"); ld.energy = e; ld.size = 0.5
    lo = bpy.data.objects.new(nm, ld); scene.collection.objects.link(lo); lo.location = loc
    lo.rotation_euler = (Vector((0.15, 0.1, 0)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
scene.render.filepath = os.path.abspath(a.out); bpy.ops.render.render(write_still=True)

# OpenCV camera: x right, y down, z forward; Blender's looks down -z with y up.
bpy.context.view_layer.update()
w2c_bl = np.array(cam.matrix_world.inverted())
w2c = np.diag([1, -1, -1, 1]) @ w2c_bl
f = cd.lens / cd.sensor_width * W
json.dump({"K": [[f, 0, W / 2], [0, f, H / 2], [0, 0, 1]], "world_to_camera_m": w2c.tolist(), "size": [W, H]},
          open(os.path.join(os.path.dirname(os.path.abspath(a.out)), "camera.json"), "w"), indent=1)
print("rendered", a.out)
