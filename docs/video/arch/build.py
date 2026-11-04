"""Architecture slides for the video: writes arch-NN.html and renders arch-NN.png (1920x1080) and
arch-NN@2x.png with headless Chrome, in the same look as ../slides.
    .venv/bin/python docs/video/arch/build.py
"""
import os, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# The slides' own head and footer, so the two sets match exactly.
src = open(os.path.join(os.path.dirname(HERE), "slides", "build.py")).read()
ns = {}
exec(src[src.index("HEAD = "):src.index("S = []")], ns)
HEAD, FOOT = ns["HEAD"], ns["FOOT"]

EXTRA = """<style>
h1 { margin:30px 0 8px; font-size:64px; }
.sub { font-size:28px; margin:0 0 26px; }
.box { background:var(--card); border:1px solid var(--line); border-radius:22px; padding:26px 30px; position:relative; }
.box h3 { font:600 34px/1.15 var(--display); margin:0 0 8px; display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.box p { margin:0; color:var(--muted); font-size:26px; line-height:1.35; }
.box.acc { border-color:rgb(57 90 246 / .7); box-shadow:0 0 0 1px rgb(57 90 246 / .35), 0 0 40px rgb(57 90 246 / .12); }
.tag { font:600 20px var(--body); color:var(--pale); background:rgb(57 90 246 / .18); border:1px solid rgb(57 90 246 / .5);
       padding:2px 12px; border-radius:999px; }
.tag.grey { color:var(--muted); background:rgb(255 255 255 / .05); border-color:var(--line); }
.n { flex:0 0 42px; width:42px; height:42px; border-radius:50%; background:var(--accent); font:700 20px var(--display);
     display:inline-grid; place-items:center; color:#fff; }
.flow { display:flex; align-items:stretch; gap:0; }
.arrow { flex:0 0 54px; display:grid; place-items:center; }
.arrow svg { width:40px; height:28px; }
.down { display:grid; place-items:center; height:46px; }
.down svg { width:28px; height:40px; }
.group { background:rgb(255 255 255 / .02); border:1px dashed #333844; border-radius:26px; padding:26px 24px; }
.group > .gh { font:600 25px var(--body); color:var(--pale); margin:0 0 14px 6px; letter-spacing:.01em; }
ul.k { margin:6px 0 0; padding:0; list-style:none; display:flex; flex-direction:column; gap:14px; }
ul.k li { font-size:26px; color:#D6D9DF; padding-left:24px; position:relative; line-height:1.32; }
ul.k li::before { content:""; position:absolute; left:2px; top:14px; width:9px; height:9px; border-radius:50%; background:var(--accent); }
.stat { font:600 27px var(--display); background:var(--card); border:1px solid var(--line); border-radius:16px; padding:12px 20px; }
.stat b { color:var(--pale); }
.stage { position:absolute; left:72px; right:72px; top:290px; bottom:96px; display:flex; flex-direction:column; justify-content:center; }
</style>"""

R = '<div class="arrow"><svg viewBox="0 0 40 28"><path d="M2 14h30M22 4l12 10-12 10" fill="none" stroke="#395AF6" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>'
L = '<div class="arrow"><svg viewBox="0 0 40 28"><path d="M38 14H8M18 4L6 14l12 10" fill="none" stroke="#395AF6" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>'
D = '<div class="down"><svg viewBox="0 0 28 40"><path d="M14 2v30M4 22l10 12 10-12" fill="none" stroke="#395AF6" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>'
META = '<span class="tag">Meta</span>'

S = []
def slide(step, body, right="Architecture"):
    # Everything under the subtitle sits in the stage, centred in the space left.
    cut = body.index("</p>", body.index('class="sub"')) + 4
    body = body[:cut] + '<div class="stage">' + body[cut:] + "</div>"
    S.append(HEAD.replace("{step}", step).replace("</head>", EXTRA + "</head>") + body + FOOT.replace("{right}", right))

# 1 The system
slide("Architecture · 1 of 4", f"""
<h1>The system</h1>
<p class="sub">A phone, one web app on Modal, and three Meta models.</p>
<div class="flow" style="align-items:center">
 <div style="flex:0 0 380px; display:flex; flex-direction:column; gap:18px">
  <div class="box"><h3>Phone browser</h3><p>Guided camera: the sheet and arrows for each angle</p></div>
  <div class="box"><h3>Result</h3><p>3D viewer, then STEP, STL and a 3MF for Bambu Studio</p></div>
 </div>
 <div style="flex:0 0 70px; display:flex; flex-direction:column; gap:110px">{R}{L}</div>
 <div class="box acc" style="flex:1">
  <h3>Web app on Modal <span class="tag grey">FastAPI · 4 CPUs</span></h3>
  <p>Takes the photos, keeps every scan on a Modal volume, and serves the files.</p>
  <div class="box" style="margin-top:18px; background:#20242B"><h3>Each scan: its own process</h3><p>The pipeline, from photos to CAD and grippers</p></div>
 </div>
 <div style="flex:0 0 70px; display:flex; flex-direction:column; gap:150px">{R}{R}</div>
 <div style="flex:0 0 470px; display:flex; flex-direction:column; gap:18px">
  <div class="box"><h3>Meta Model API <span class="tag grey">HTTPS</span></h3>
   <ul class="k"><li>Muse Spark {META}</li><li>SAM 3.1 {META}</li></ul></div>
  <div class="box"><h3>Modal GPU <span class="tag grey">L40S</span></h3>
   <ul class="k"><li>SAM 3D Objects {META}</li><li>Open weights</li></ul></div>
 </div>
</div>
<div style="display:flex; gap:16px; margin-top:56px; align-items:center">
 <span style="font:600 24px var(--body); color:var(--muted); margin-right:6px">Who can run it</span>
 <div class="stat">Judges' passcode <b>50 a day</b></div>
 <div class="stat">Your own Meta key <b>200 a day</b></div>
 <div class="stat">Bevell Unlimited key <b>20 a day</b></div>
</div>""")

# 2 Photos to a measured model
slide("Architecture · 2 of 4", f"""
<h1>Photos to a measured model</h1>
<p class="sub">Every size comes from the photos. The models make choices, not measurements.</p>
<div class="flow">
 <div class="box" style="flex:1.15"><h3><span class="n">1</span>11 photos</h3><p>Guided, on a printed A4 sheet</p></div>{R}
 <div class="box" style="flex:1.3"><h3><span class="n">2</span>22 ArUco markers</h3><p>The focal length, and where each photo was taken</p></div>{R}
 <div class="box" style="flex:1.2"><h3><span class="n">3</span>Muse Spark {META}</h3><p>Plans: what it is, the prompt, which photos to drop</p></div>{R}
 <div class="box" style="flex:1.2"><h3><span class="n">4</span>SAM 3.1 {META}</h3><p>Masks every photo; zooms in again on small objects</p></div>
</div>
{D}
<div class="flow">
 <div class="box" style="flex:1"><h3><span class="n">5</span>Visual hull</h3><p>The masks carve a voxel block</p></div>{R}
 <div class="box" style="flex:1.1"><h3><span class="n">6</span>Shape router</h3><p>Turned, prismatic or freeform</p></div>{R}
 <div class="box acc" style="flex:1.35"><h3><span class="n">7</span>SAM 3D Objects {META}</h3><p>The whole shape, fitted to the photos: scale, yaw, tilt, stretch</p></div>{R}
 <div class="box" style="flex:1.25"><h3><span class="n">8</span>Keep the best</h3><p>Scored against every mask; SAM 3D kept within 0.08 of the hull</p></div>
</div>
<div style="display:flex; gap:16px; margin-top:44px">
 <div class="stat">Cameras within <b>0.2 to 0.3 mm</b></div>
 <div class="stat">Size within <b>2 mm</b> on 12 of 15 test objects</div>
</div>""")

# 3 Model to CAD
slide("Architecture · 3 of 4", f"""
<h1>Model to CAD</h1>
<p class="sub">CAD that fits the object, not one mesh for everything.</p>
<div class="flow" style="align-items:center">
 <div style="flex:1; display:flex; flex-direction:column; gap:16px">
  <div class="box"><h3>Prismatic</h3><p>Sketch and extrude; level heights and hole diameters named</p></div>
  <div class="box"><h3>Turned</h3><p>A revolved profile</p></div>
  <div class="box"><h3>Freeform</h3><p>Smooth NURBS: QuadriFlow quads, then bicubic patches</p></div>
 </div>
 {R}
 <div class="box acc" style="flex:0 0 430px">
  <h3>Out to the phone</h3>
  <ul class="k"><li>STEP and STL, true size</li><li>A holder: a pocket with 0.4 mm clearance</li><li>3MF that opens in Bambu Studio</li></ul>
 </div>
</div>
{D}
<div class="box" style="display:flex; gap:28px; align-items:center">
 <div style="flex:0 0 470px"><h3>Muse Spark CAD agent {META}</h3><p style="margin-bottom:6px"><span class="tag grey">On request</span></p>
  <p>Writes the object as a feature tree</p></div>
 <ul class="k" style="flex:1; display:grid; grid-template-columns:1fr 1fr; gap:12px 34px">
  <li>Revolve, extrude, loft, sweep, shell, fillet</li><li>Sees where it misses, photo by photo, and revises</li>
  <li>Dimensions tuned against every photo</li><li>A CadQuery program and a Fusion 360 timeline</li></ul>
</div>""")

# 4 Custom grippers
slide("Architecture · 4 of 4", f"""
<h1>Custom grippers <span class="tag" style="font-size:22px; vertical-align:middle">Beta · SO-101</span> <span class="tag grey" style="font-size:22px; vertical-align:middle">Deterministic, no AI guessing</span></h1>
<p class="sub">From the measured scissors to two parts that replace the SO-101's own.</p>
<div class="flow">
 <div class="group" style="flex:1"><div class="gh">Read the tool</div>
  <ul class="k">
   <li>Outline from the overhead masks</li>
   <li>Finger holes from SAM 3D where it agrees on the outside edge</li>
   <li>Finger loops, split where they touch</li>
   <li>Pivot: Hough circles on the flattened top photo, the innermost one</li>
  </ul></div>{R}
 <div class="group" style="flex:1.12"><div class="gh">Design the parts</div>
  <ul class="k">
   <li>Hinge from the SO-101's own MJCF</li>
   <li>Pivot on the hinge: blades open with the jaw</li>
   <li>A snap clip per loop: one-sided lip, 0.4 mm clearance</li>
   <li>Scissors cut out, moving half's sweep too</li>
   <li>Rounded arms, 4 mm fillet by SDF closing</li>
  </ul></div>{R}
 <div class="group" style="flex:0.95"><div class="gh">Check and ship</div>
  <ul class="k">
   <li>Arrangement search until nothing collides</li>
   <li>MuJoCo: jaw 25.8°, blades 25.8°</li>
   <li>Print plate 3MF, both parts flat on the bed</li>
  </ul></div>
</div>""")


def render(html, png, scale):
    subprocess.run([CHROME, "--headless=new", "--hide-scrollbars", "--disable-gpu", f"--force-device-scale-factor={scale}",
                    "--window-size=1920,1080", "--virtual-time-budget=4000", f"--screenshot={png}", "file://" + html],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


for n, html in enumerate(S, 1):
    p = os.path.join(HERE, f"arch-{n:02d}.html"); open(p, "w").write(html)
    render(p, os.path.join(HERE, f"arch-{n:02d}.png"), 1)
    render(p, os.path.join(HERE, f"arch-{n:02d}@2x.png"), 2)
print("rendered", len(S))
