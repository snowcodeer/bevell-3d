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
.box.big h3 { font-size:42px; margin:0; } .box.big p { font-size:31px; margin-top:10px; } .box.big { padding:36px 38px; }
.col { display:flex; flex-direction:column; gap:18px; }
.stage { position:absolute; left:72px; right:72px; top:250px; bottom:96px; display:flex; flex-direction:column; justify-content:center; }
</style>"""

R = '<div class="arrow"><svg viewBox="0 0 40 28"><path d="M2 14h30M22 4l12 10-12 10" fill="none" stroke="#395AF6" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>'
L = '<div class="arrow"><svg viewBox="0 0 40 28"><path d="M38 14H8M18 4L6 14l12 10" fill="none" stroke="#395AF6" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>'
D = '<div class="down"><svg viewBox="0 0 28 40"><path d="M14 2v30M4 22l10 12 10-12" fill="none" stroke="#395AF6" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>'
META = '<span class="tag">Meta</span>'

S = []
def slide(step, body, right="Architecture"):
    # Everything under the subtitle sits in the stage, centred in the space left.
    cut = (body.index("</p>", body.index('class="sub"')) + 4) if 'class="sub"' in body else (body.index("</h1>") + 5)
    body = body[:cut] + '<div class="stage">' + body[cut:] + "</div>"
    S.append(HEAD.replace("{step}", step).replace("</head>", EXTRA + "</head>") + body + FOOT.replace("{right}", right))

# 1 The system
slide("Architecture · 1 of 4", f"""
<h1>The system</h1>
<div class="flow" style="align-items:center">
 <div class="box big" style="flex:0 0 340px"><h3>Phone</h3><p>Guided camera</p></div>
 <div style="flex:0 0 70px; display:flex; flex-direction:column; gap:40px">{R}{L}</div>
 <div class="box big acc" style="flex:1"><h3>Web app on Modal</h3><p>Each scan, its own process</p></div>
 <div style="flex:0 0 70px; display:flex; flex-direction:column; gap:150px">{R}{R}</div>
 <div style="flex:0 0 520px; display:flex; flex-direction:column; gap:26px">
  <div class="box big"><h3>Meta Model API</h3><p>Muse Spark {META}<br>SAM 3.1 {META}</p></div>
  <div class="box big"><h3>Modal L40S GPU</h3><p>SAM 3D Objects {META}</p></div>
 </div>
</div>""")

# 2 Photos to a measured model
slide("Architecture · 2 of 4", f"""
<h1>Photos to a measured model</h1>
<div class="flow">
 <div class="box big" style="flex:1"><h3><span class="n">1</span>11 photos</h3><p>Guided, on a sheet</p></div>{R}
 <div class="box big" style="flex:1"><h3><span class="n">2</span>ArUco markers</h3><p>Scale and camera</p></div>{R}
 <div class="box big" style="flex:1"><h3><span class="n">3</span>Muse Spark {META}</h3><p>Plans the scan</p></div>{R}
 <div class="box big" style="flex:1"><h3><span class="n">4</span>SAM 3.1 {META}</h3><p>Masks every photo</p></div>
</div>
{D}
<div class="flow">
 <div class="box big" style="flex:1"><h3><span class="n">5</span>Visual hull</h3><p>Carved by the masks</p></div>{R}
 <div class="box big acc" style="flex:1.15"><h3><span class="n">6</span>SAM 3D {META}</h3><p>Fitted to the photos</p></div>{R}
 <div class="box big" style="flex:1"><h3><span class="n">7</span>Best fit wins</h3><p>Scored on every mask</p></div>
</div>
<div style="display:flex; gap:16px; margin-top:44px"><div class="stat">Cameras within <b>0.2 to 0.3 mm</b></div></div>""")

# 3 Model to CAD
slide("Architecture · 3 of 4", f"""
<h1>Model to CAD</h1>
<div class="flow" style="align-items:center">
 <div style="flex:1; display:flex; flex-direction:column; gap:22px">
  <div class="box big"><h3>Prismatic</h3><p>Sketch and extrude</p></div>
  <div class="box big"><h3>Turned</h3><p>Revolve</p></div>
  <div class="box big"><h3>Freeform</h3><p>Smooth NURBS</p></div>
 </div>
 {R}
 <div style="flex:1; display:flex; flex-direction:column; gap:22px">
  <div class="box big"><h3>Muse Spark CAD agent {META}</h3><p>Editable feature tree</p></div>
  <div class="box big acc"><h3>STEP, STL, 3MF</h3><p>Straight to Bambu Studio</p></div>
 </div>
</div>""")

# 4 Custom grippers
slide("Architecture · 4 of 4", f"""
<h1>Custom grippers <span class="tag" style="font-size:24px; vertical-align:middle">Beta · SO-101</span></h1>
<div class="flow">
 <div class="group" style="flex:1"><div class="gh">Read the tool</div>
  <div class="col"><div class="box big"><h3>Outline + SAM 3D holes</h3></div><div class="box big"><h3>Finger loops</h3></div><div class="box big"><h3>Pivot = screw</h3></div></div></div>{R}
 <div class="group" style="flex:1"><div class="gh">Design the parts</div>
  <div class="col"><div class="box big"><h3>Pivot on the hinge</h3></div><div class="box big"><h3>Snap clip per loop</h3></div><div class="box big"><h3>Scissors cut out</h3></div></div></div>{R}
 <div class="group" style="flex:1"><div class="gh">Check and ship</div>
  <div class="col"><div class="box big"><h3>4 mm fillets</h3></div><div class="box big acc"><h3>MuJoCo: no collisions</h3></div><div class="box big"><h3>Print plate 3MF</h3></div></div></div>
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
