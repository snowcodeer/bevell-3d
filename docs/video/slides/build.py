"""Writes slide-NN.html and renders slide-NN.png (1920x1080) and slide-NN@2x.png with headless Chrome.
    .venv/bin/python docs/video/slides/build.py
"""
import os, subprocess, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
URL = "nataliechan1963--bevell-3d-web.us-east.modal.run"

HEAD = """<!doctype html><html lang="en-GB"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root { --bg:#14161A; --card:#1B1E24; --line:#2A2E36; --fg:#fff; --muted:#9AA0AA; --accent:#395AF6; --pale:#8095F9;
        --display:"Outfit","Avenir Next",sans-serif; --body:"Inter",-apple-system,sans-serif; }
* { box-sizing:border-box; }
html,body { margin:0; width:1920px; height:1080px; overflow:hidden; }
body { background:var(--bg); color:var(--fg); font:26px/1.4 var(--body); padding:52px 72px 0; position:relative;
       background-image: radial-gradient(1200px 600px at 80% -10%, rgb(57 90 246 / .16), transparent 60%),
                         radial-gradient(900px 500px at 0% 110%, rgb(57 90 246 / .08), transparent 60%); }
.top { display:flex; align-items:center; justify-content:space-between; }
.brand { display:flex; align-items:center; gap:14px; } .brand .mark { height:42px; } .brand .word { height:20px; }
.badge { font:600 18px var(--body); color:var(--pale); background:rgb(57 90 246 / .16); padding:4px 13px; border-radius:999px; }
.step { font:600 20px var(--body); color:var(--muted); }
h1 { font:700 72px/1.04 var(--display); margin:40px 0 10px; letter-spacing:-0.015em; max-width:1700px; }
h1 .acc { color:var(--pale); }
.sub { font:500 32px/1.3 var(--display); color:var(--muted); margin:0 0 30px; max-width:1500px; }
.meta { font:600 20px var(--body); color:var(--pale); background:rgb(57 90 246 / .18); border:1px solid rgb(57 90 246 / .5);
        padding:3px 14px; border-radius:999px; vertical-align:middle; margin-left:14px; position:relative; top:-10px; }
.frame { border-radius:24px; overflow:hidden; border:1px solid var(--line); background:var(--card); position:relative; }
.frame img { display:block; width:100%; height:100%; object-fit:cover; }
.frame.contain img { object-fit:contain; }
.frame.light { background:#F2F3F5; }
.cap { position:absolute; left:18px; bottom:16px; font:600 22px var(--body); color:#fff; background:rgb(20 22 26 / .78);
       padding:6px 14px; border-radius:12px; }
.frame.light .cap { color:#14161A; background:rgb(255 255 255 / .85); }
.row { display:flex; gap:28px; }
.pills { display:flex; gap:16px; flex-wrap:wrap; margin-top:26px; }
.pill { font:600 26px var(--display); background:var(--card); border:1px solid var(--line); border-radius:18px; padding:16px 24px; }
.pill b { color:var(--pale); font-weight:700; }
.list { display:flex; flex-direction:column; gap:18px; }
.li { display:flex; gap:18px; align-items:flex-start; background:var(--card); border:1px solid var(--line); border-radius:20px; padding:20px 24px; }
.li .n { flex:0 0 40px; height:40px; border-radius:50%; background:var(--accent); font:700 21px var(--display); display:grid; place-items:center; }
.li h3 { font:600 30px/1.15 var(--display); margin:2px 0 4px; } .li p { margin:0; color:var(--muted); font-size:24px; }
footer { position:absolute; left:72px; right:72px; bottom:30px; display:flex; justify-content:space-between; font:500 19px var(--body); color:var(--muted); }
</style></head><body>
<div class="top"><div class="brand"><img class="mark" src="logo-icon.svg"><img class="word" src="bevell-wordmark.svg"><span class="badge">3D</span></div><div class="step">{step}</div></div>
"""
FOOT = """<footer><span>Bevell 3D · Meta AI hackathon</span><span>{right}</span></footer></body></html>"""

S = []
def slide(step, body, right=""):
    S.append(HEAD.replace("{step}", step) + body + FOOT.replace("{right}", right))

# 1 hook
slide("", """
<div style="display:flex; gap:40px; align-items:center; margin-top:80px">
 <div style="flex:1.15">
  <h1 style="font-size:104px; margin:0 0 24px">Robotics is<br>moving fast.</h1>
  <h1 style="font-size:104px; margin:0" class=""><span class="acc">Prototyping should<br>move faster.</span></h1>
 </div>
 <div class="frame" style="flex:0.85; height:620px"><img src="img/sim_open.jpg"></div>
</div>""")
# 2 problem
slide("The problem", """
<h1>A robot arm can't use a human tool.</h1>
<p class="sub">Custom tooling for each one is an afternoon of CAD, a print, and another try.</p>
<div class="row" style="height:640px">
 <div class="frame" style="flex:1; background:#E9ECF2"><img src="img/top_photo.jpg" style="object-fit:contain"><span class="cap">A pair of scissors</span></div>
 <div class="frame light contain" style="flex:1"><img src="img/r_grippers_crop.png"><span class="cap">What the SO-101 needs to use them</span></div>
</div>""")
# 3 photos
slide("1 · Photos", """
<h1>Photos in. CAD out.</h1>
<p class="sub">Phone photos of the tool on a printed sheet. The app guides every angle.</p>
<div class="frame" style="height:700px"><img src="img/photos.jpg"></div>""")
# 4 cameras
slide("2 · Scale and cameras", """
<h1>Every photo, measured.</h1>
<p class="sub">The sheet's squares give each photo its scale and its camera, to a fraction of a millimetre.</p>
<div class="row" style="height:680px">
 <div class="frame" style="flex:0.62"><img src="img/markers.jpg"><span class="cap">The squares, drawn back through the camera</span></div>
 <div class="frame" style="flex:1; background:#14161A"><img src="img/cameras.png" style="object-fit:contain"><span class="cap">Every camera, placed round the sheet</span></div>
</div>""")
# 5 masks
slide("3 · Segmentation", """
<h1>SAM 3.1 finds the object in every photo<span class="meta">Meta</span></h1>
<p class="sub">Muse Spark names it and writes the prompt. The masks are the measurement.</p>
<div class="frame" style="height:700px"><img src="img/masks.jpg"></div>""")
# 6 sam3d
slide("4 · The whole shape", """
<h1>SAM 3D builds the whole shape<span class="meta">Meta</span></h1>
<p class="sub">Including the sides no photo sees, then sized and placed by every photo.</p>
<div class="row" style="height:660px">
 <div class="frame light contain" style="flex:1"><img src="img/r_hull_crop.png"><span class="cap">Carved from the photos' outlines</span></div>
 <div class="frame light contain" style="flex:1"><img src="img/r_sam3d_crop.png"><span class="cap">SAM 3D Objects, fitted to the photos</span></div>
</div>""")
# 7 composite
slide("5 · Two models, each where it's right", """
<h1>The photos' edge, SAM 3D's finger holes.</h1>
<p class="sub">On clear plastic the masks fill the holes. SAM 3D sees them. Each model is used where it's right.</p>
<div class="row" style="height:660px">
 <div class="frame" style="flex:1; background:#DADDE2"><img src="img/clear_masks_only.jpg" style="object-fit:contain"><span class="cap">Masks only: the holes filled in</span></div>
 <div class="frame" style="flex:1; background:#DADDE2"><img src="img/clear_composite.jpg" style="object-fit:contain"><span class="cap">Combined: true to the scissors</span></div>
</div>""")
# 8 pivot
slide("6 · The pivot", """
<h1>The pivot is the screw.</h1>
<p class="sub">Found in the photo from above, then put on the gripper's own hinge, so the blades open with the jaw.</p>
<div class="frame" style="height:680px; background:#E9ECF2"><img src="img/pivot.jpg" style="object-fit:contain"></div>""")
# 9 grippers
slide("7 · Custom grippers", """
<h1>Grippers designed, not guessed.</h1>
<div class="row" style="height:780px; margin-top:30px">
 <div class="frame light contain" style="flex:1.15"><img src="img/r_grippers_crop.png"><span class="cap">Two new SO-101 parts, the scissors in place</span></div>
 <div style="flex:0.85; display:flex; flex-direction:column; gap:22px">
  <div class="frame" style="height:360px; background:#14161A; display:flex; align-items:center; gap:26px; padding:22px 28px">
   <img src="img/clip_section.png" style="flex:0 0 330px; width:330px; height:300px; object-fit:contain">
   <div style="flex:1; min-width:0; display:flex; flex-direction:column; gap:12px; font:500 24px var(--body); color:var(--muted)">
     <div style="font:600 28px var(--display); color:#fff">A clip, cut through</div>
     <div><span style="color:#C8CCD4">Grey:</span> the finger loop</div>
     <div><span style="color:var(--pale)">Blue:</span> the clip, mouth at the top</div>
     <div>A lip at the mouth snaps it in</div>
     <div>0.4 mm clearance all round</div>
   </div></div>
  <div class="list">
   <div class="li"><div class="n">1</div><div><h3>Pivot on the hinge</h3><p>Blades open as far as the jaw</p></div></div>
   <div class="li"><div class="n">2</div><div><h3>A snap clip per loop</h3><p>0.4 mm clearance, a 0.5 mm lip</p></div></div>
   <div class="li"><div class="n">3</div><div><h3>Stock screws, stock holes</h3><p>Unscrew two parts, fit two new ones</p></div></div>
  </div>
 </div>
</div>""")
# 10 mujoco
slide("8 · Simulation", """
<h1>Tested in MuJoCo first.</h1>
<div class="row" style="height:600px; margin-top:34px">
 <div class="frame" style="flex:1"><img src="img/sim_closed.jpg"><span class="cap">Gripper closed: blades shut</span></div>
 <div class="frame" style="flex:1"><img src="img/sim_open.jpg"><span class="cap">Gripper open: blades open</span></div>
</div>
<div class="pills"><div class="pill">Jaw <b>25.8°</b></div><div class="pill">Blades <b>25.8°</b></div><div class="pill"><b>0</b> collisions</div><div class="pill">SO-101 model from its own files</div></div>""")
# 12 close (11 is the architecture png)
slide("", f"""
<div style="margin-top:120px">
 <h1 style="font-size:96px">Built in three days.</h1>
 <p class="sub" style="font-size:40px; color:var(--pale)">Muse Spark, SAM 3.1 and SAM 3D, on the Meta Model API and Modal.</p>
 <div class="pills" style="margin-top:60px"><div class="pill">Try it: <b>{URL}</b></div></div>
 <div class="pills"><div class="pill">Beta: SO-101 and scissors for now</div><div class="pill">Open source on GitHub</div></div>
</div>""", "Photos in. CAD out.")

def render(html, png, scale):
    subprocess.run([CHROME, "--headless=new", "--hide-scrollbars", "--disable-gpu", f"--force-device-scale-factor={scale}",
                    "--window-size=1920,1080", "--virtual-time-budget=4000", f"--screenshot={png}", "file://" + html],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

order = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12]
for n, html in zip(order, S):
    p = os.path.join(HERE, f"slide-{n:02d}.html"); open(p, "w").write(html)
    render(p, os.path.join(HERE, f"slide-{n:02d}.png"), 1)
    render(p, os.path.join(HERE, f"slide-{n:02d}@2x.png"), 2)
arch = os.path.join(os.path.dirname(HERE), "architecture.png")
shutil.copy(arch, os.path.join(HERE, "slide-11.png"))
shutil.copy(arch.replace(".png", "@2x.png"), os.path.join(HERE, "slide-11@2x.png"))
print("rendered", len(order) + 1)
