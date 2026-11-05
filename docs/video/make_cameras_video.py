"""The cameras-and-SAM-3D clip for the hackathon video: every measured camera round the sheet with
its photo and SAM 3.1 mask, then SAM 3D's scissors on the sheet. Orbiting, Bevell look.

    .venv/bin/python docs/video/make_cameras_video.py            # prep, Blender render, encode
Writes docs/video/cameras_sam3d.mp4. The scene is built in Blender (Eevee) from a JSON this
script prepares; frames go to a temporary folder.
"""
import json, os, pickle, subprocess, sys, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
SCAN = os.path.join(ROOT, "out", "black_scissors")
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
FONTS = os.environ.get("BEVELL_FONTS", "/private/tmp/claude-501/-Users-nataliechan-Projects-bevell/a2b2193e-bc31-4c51-853a-b32a3ad2f03a/scratchpad/fonts")
FPS, SECONDS, W, H = 30, 14, 1920, 1080
ACCENT = (57, 90, 246); ACCENT_LIGHT = (100, 126, 248)
DEPTH = 100.0                      # mm from a camera to its image plane in the scene


def prep(work):
    import cv2
    vp = pickle.load(open(os.path.join(SCAN, "views.pkl"), "rb"))
    Wi, Hi = vp["size"]
    cams = []
    ctr = np.array([148.5, 105.0])
    for v, m in zip(vp["views"], vp["masks"]):
        R = cv2.Rodrigues(v["rv"])[0]; t = np.asarray(v["tv"], float).reshape(3); K = np.asarray(v["K"], float)
        C = -R.T @ t
        def ray(u, w):
            return C + DEPTH * (R.T @ np.array([(u - K[0, 2]) / K[0, 0], (w - K[1, 2]) / K[1, 1], 1.0]))
        corners = [ray(0, 0), ray(Wi, 0), ray(Wi, Hi), ray(0, Hi)]          # image TL, TR, BR, BL
        img = cv2.imread(os.path.join(SCAN, "photos", v["name"] + ".jpg"))
        if img is None or (img.shape[1], img.shape[0]) != (Wi, Hi):
            img = cv2.resize(img, (Wi, Hi))
        mk = m.astype(bool)
        if mk.shape != img.shape[:2]:
            mk = cv2.resize(mk.astype(np.uint8), (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
        tint = img.copy(); tint[mk] = (0.6 * img[mk] + 0.4 * np.array(ACCENT[::-1])).astype(np.uint8)
        cs, _ = cv2.findContours(mk.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(tint, cs, -1, ACCENT_LIGHT[::-1], 5, cv2.LINE_AA)
        tint = cv2.resize(tint, (Wi // 2, Hi // 2), interpolation=cv2.INTER_AREA)
        p = os.path.join(work, v["name"] + ".png"); cv2.imwrite(p, tint)
        az = float(np.arctan2(C[1] - ctr[1], C[0] - ctr[0]))
        cams.append({"name": v["name"], "C": C.tolist(), "corners": [c.tolist() for c in corners], "image": p, "az": az})
    a0 = cams[0]["az"]
    cams.sort(key=lambda c: (c["az"] - a0) % (2 * np.pi))             # appear in order round the sheet
    # The capture sheet's page as a picture (poppler), landscape like the sheet frame.
    subprocess.run(["pdftoppm", "-png", "-r", "200", "-f", "1", "-l", "1", "-singlefile",
                    os.path.join(ROOT, "assets", "bevell_capture_sheet.pdf"), os.path.join(work, "sheet")], check=True)
    sheet = os.path.join(work, "sheet.png")
    im = cv2.imread(sheet)
    if im.shape[0] > im.shape[1]:
        cv2.imwrite(sheet, cv2.rotate(im, cv2.ROTATE_90_COUNTERCLOCKWISE))
    scene = {"cams": cams, "sheet": sheet, "page_mm": [297.0, 210.0],
             "sam3d": os.path.join(SCAN, "sam3d_fitted.stl"), "frames": FPS * SECONDS, "fps": FPS, "res": [W, H],
             "out": os.path.join(work, "frames", "f_")}
    json.dump(scene, open(os.path.join(work, "scene.json"), "w"))
    return os.path.join(work, "scene.json")


BLENDER_SCRIPT = r'''
import bpy, json, math, sys
from mathutils import Vector
S = json.load(open(sys.argv[sys.argv.index("--") + 1]))
FPS = S["fps"]; N = S["frames"]
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
sc.render.resolution_x, sc.render.resolution_y = S["res"]; sc.render.fps = FPS
sc.frame_start, sc.frame_end = 1, N
try: sc.eevee.taa_render_samples = 16
except Exception: pass
sc.view_settings.view_transform = "Standard"
sc.render.image_settings.file_format = "PNG"; sc.render.filepath = S["out"]
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
bg = w.node_tree.nodes["Background"]; bg.inputs[0].default_value = (0.0070, 0.0080, 0.0103, 1); bg.inputs[1].default_value = 1.0
def srgb(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c) + (1.0,)
def emission_mat(name, color=None, image=None, strength=1.0, fade=None):
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); em = nt.nodes.new("ShaderNodeEmission"); em.inputs[1].default_value = strength
    if image:
        tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = bpy.data.images.load(image); nt.links.new(tex.outputs[0], em.inputs[0])
    else:
        em.inputs[0].default_value = color
    tr = nt.nodes.new("ShaderNodeBsdfTransparent"); mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(tr.outputs[0], mix.inputs[1]); nt.links.new(em.outputs[0], mix.inputs[2]); nt.links.new(mix.outputs[0], out.inputs[0])
    mix.inputs[0].default_value = 1.0
    try: m.surface_render_method = "BLENDED"
    except Exception: m.blend_method = "BLEND"
    return m, mix
def key(sock, frame, value):
    sock.default_value = value; sock.keyframe_insert("default_value", frame=frame)
# The sheet, lying at z = 0, x along 297 mm, y up the page.
pw, ph = S["page_mm"]
bpy.ops.mesh.primitive_plane_add(size=1); sheet = bpy.context.object; sheet.scale = (pw, ph, 1); sheet.location = (pw / 2, ph / 2, 0)
sm, _ = emission_mat("sheet", image=S["sheet"], strength=0.95); sheet.data.materials.append(sm)
# Cameras: a thin frustum (tubes) and the photo on its image plane, growing out of the camera.
accent = srgb("#395AF6")
line_mat, _ = emission_mat("lines", color=accent, strength=3.0)
cams = S["cams"]; n = len(cams)
t_in0, t_in1 = 2.0, 8.0
photo_mixes = []
for i, c in enumerate(cams):
    C = Vector(c["C"]); P = [Vector(p) for p in c["corners"]]
    root = bpy.data.objects.new("cam%d" % i, None); sc.collection.objects.link(root); root.location = C
    cu = bpy.data.curves.new("fr%d" % i, "CURVE"); cu.dimensions = "3D"; cu.bevel_depth = 0.9; cu.bevel_resolution = 2
    for a, b in [(0, 1), (1, 2), (2, 3), (3, 0)]:
        sp = cu.splines.new("POLY"); sp.points.add(1); sp.points[0].co = (*(P[a] - C), 1); sp.points[1].co = (*(P[b] - C), 1)
    for a in range(4):
        sp = cu.splines.new("POLY"); sp.points.add(1); sp.points[0].co = (0, 0, 0, 1); sp.points[1].co = (*(P[a] - C), 1)
    fo = bpy.data.objects.new("frust%d" % i, cu); fo.data.materials.append(line_mat); sc.collection.objects.link(fo); fo.parent = root
    me = bpy.data.meshes.new("img%d" % i)
    me.from_pydata([tuple(p - C) for p in P], [], [(0, 1, 2, 3)]); me.update()
    uv = me.uv_layers.new(); 
    for li, (u, v) in zip(range(4), [(0, 1), (1, 1), (1, 0), (0, 0)]):
        uv.data[li].uv = (u, v)
    io = bpy.data.objects.new("photo%d" % i, me); sc.collection.objects.link(io); io.parent = root
    pm, mix = emission_mat("photo%d" % i, image=c["image"], strength=1.0); io.data.materials.append(pm); photo_mixes.append(mix)
    f0 = int(FPS * (t_in0 + (t_in1 - t_in0 - 0.6) * i / max(1, n - 1))) + 1
    root.scale = (0.001, 0.001, 0.001); root.keyframe_insert("scale", frame=f0)
    root.scale = (1, 1, 1); root.keyframe_insert("scale", frame=f0 + 12)
    root.keyframe_insert("scale", frame=int(FPS * 9.8))                   # then back into the camera point
    root.scale = (0.001, 0.001, 0.001); root.keyframe_insert("scale", frame=int(FPS * 10.8))
    key(mix.inputs[0], 1, 1.0)
    key(mix.inputs[0], int(FPS * 8.0), 1.0); key(mix.inputs[0], int(FPS * 10.0), 0.0)
# SAM 3D's scissors rising onto the sheet.
bpy.ops.wm.stl_import(filepath=S["sam3d"]); sam = bpy.context.selected_objects[0]
bpy.ops.object.shade_smooth()
bb = [sam.matrix_world @ Vector(v) for v in sam.bound_box]
cx = sum(v.x for v in bb) / 8; cy = sum(v.y for v in bb) / 8; z0 = min(v.z for v in bb)
bpy.context.scene.cursor.location = (cx, cy, z0); bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
smat = bpy.data.materials.new("sam"); smat.use_nodes = True
pb = smat.node_tree.nodes["Principled BSDF"]; pb.inputs["Base Color"].default_value = srgb("#5B7BFF"); pb.inputs["Roughness"].default_value = 0.3
try:
    pb.inputs["Emission Color"].default_value = srgb("#5B7BFF"); pb.inputs["Emission Strength"].default_value = 0.35
except Exception:
    pass
sam.data.materials.append(smat)
fs = int(FPS * 10.0); sam.scale = (1, 1, 0.001); sam.keyframe_insert("scale", frame=fs)
sam.scale = (1, 1, 1); sam.keyframe_insert("scale", frame=fs + 24)
sam.hide_render = True; sam.keyframe_insert("hide_render", frame=fs - 1); sam.hide_render = False; sam.keyframe_insert("hide_render", frame=fs)
for fc in (sam.animation_data.action.fcurves if hasattr(sam.animation_data.action, "fcurves") else []):
    for kp in fc.keyframe_points: kp.interpolation = "CONSTANT" if fc.data_path == "hide_render" else "BEZIER"
# Light for the scissors.
ld = bpy.data.lights.new("key", "AREA"); ld.energy = 3.0e6; ld.size = 600
lo = bpy.data.objects.new("key", ld); sc.collection.objects.link(lo); lo.location = (150, -300, 900); lo.rotation_euler = (math.radians(20), 0, 0)
ld2 = bpy.data.lights.new("fill", "AREA"); ld2.energy = 1.2e6; ld2.size = 800
lo2 = bpy.data.objects.new("fill", ld2); sc.collection.objects.link(lo2); lo2.location = (600, 600, 700)
lo2.rotation_euler = (math.radians(-35), math.radians(35), 0)
# The orbiting camera, keyed every few frames: about 75 degrees round the scene at 38 degrees
# elevation, aimed at the cameras' middle, then easing in onto the sheet for SAM 3D's scissors.
cd = bpy.data.cameras.new("cam"); cd.clip_start = 5; cd.clip_end = 20000; cd.sensor_width = 36
co = bpy.data.objects.new("cam", cd); sc.collection.objects.link(co); sc.camera = co
T1, T2 = Vector((150, 140, 150)), Vector((150, 108, 0))
el, a0, sweep = math.radians(38), math.radians(-100), math.radians(75)
ease = lambda x: 0.5 - 0.5 * math.cos(math.pi * min(1.0, max(0.0, x)))
prev = None
for f in list(range(1, N + 1, 3)) + [N]:
    tt = (f - 1) / FPS
    k = ease((tt - 9.6) / 4.0)
    tgt = T1.lerp(T2, k); dist = 1750 - 1000 * k; az = a0 + sweep * (f - 1) / (N - 1)
    loc = tgt + dist * Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)))
    co.location = loc
    q = (tgt - loc).to_track_quat("-Z", "Y")
    e = q.to_euler("XYZ", prev) if prev is not None else q.to_euler("XYZ"); prev = e
    co.rotation_euler = e; co.keyframe_insert("location", frame=f); co.keyframe_insert("rotation_euler", frame=f)
    cd.lens = 30 + 14 * k; cd.keyframe_insert("lens", frame=f)
frames = sys.argv[sys.argv.index("--") + 2] if len(sys.argv) > sys.argv.index("--") + 2 else ""
if frames:
    for f in [int(x) for x in frames.split(",")]:
        sc.frame_set(f); sc.render.filepath = S["out"] + "%04d" % f; bpy.ops.render.render(write_still=True)
else:
    bpy.ops.render.render(animation=True)
'''


def captions(work):
    from PIL import Image, ImageDraw, ImageFont
    f600 = ImageFont.truetype(os.path.join(FONTS, "Inter-600.ttf"), 34)
    fpill = ImageFont.truetype(os.path.join(FONTS, "Inter-600.ttf"), 22)
    out = []
    for i, (text, pill) in enumerate([("Every photo, measured: camera position from the sheet", False),
                                      ("SAM 3D · the whole shape", True)]):
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        x, y = 64, H - 96
        if pill:
            tw = d.textlength("Meta", font=fpill)
            d.rounded_rectangle((x, y + 2, x + tw + 28, y + 40), radius=20, fill=(57, 90, 246, 60), outline=(57, 90, 246, 255), width=2)
            d.text((x + 14, y + 8), "Meta", font=fpill, fill=(128, 149, 249, 255)); x += tw + 44
        d.text((x, y), text, font=f600, fill=(255, 255, 255, 255))
        p = os.path.join(work, "cap%d.png" % i); im.save(p); out.append(p)
    return out


def main():
    work = tempfile.mkdtemp(prefix="camvid-"); os.makedirs(os.path.join(work, "frames"))
    scene = prep(work)
    bs = os.path.join(work, "scene.py"); open(bs, "w").write(BLENDER_SCRIPT)
    test = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--test=")]
    args = [BLENDER, "-b", "-P", bs, "--", scene] + (test or [])
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL if not test else None)
    if test:
        print(work); return
    c0, c1 = captions(work)
    out = os.path.join(HERE, "cameras_sam3d.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(work, "frames", "f_%04d.png"),
                    "-i", c0, "-i", c1, "-filter_complex",
                    "[0][1]overlay=enable='between(t,2.2,9.6)'[a];[a][2]overlay=enable='between(t,10.4,14)'",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", out], check=True)
    print(out)


if __name__ == "__main__":
    main()
