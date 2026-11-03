"""Build the results page (one HTML file, images inlined) from out/results/.

    .venv/bin/python -m tools.results_page /path/to/page.html
"""
import base64, html, json, sys

R = "out/results"
NAMES = {"mario": "Mario figure", "mug": "Mug with handle", "bottle": "Vitamin bottle", "tape": "Tape roll", "mouse": "White mouse"}


def img(name):
    return "data:image/jpeg;base64," + base64.b64encode(open(f"{R}/{name}", "rb").read()).decode()


def mm(v):
    return " × ".join(f"{x:.1f}" for x in v) if v else "–"


def verdict(h):
    if h["max_penetration_mm"] <= 0.35:
        return "ok", "Drops in"
    if h["share_colliding_over_0.2mm"] <= 0.03:
        return "snug", "One snug spot"
    return "bad", "Too tight"


CAD_KIND = {"revolved": "Revolved profile (editable)", "lofted": "Lofted sections (editable)", "mesh": "Mesh body in STEP"}


def card(r, c):
    kind, label = verdict(c["holder"])
    used = {"hull": "built from the photos", "sam3d": "SAM 3D, fitted to the photos", "revolved": "round profile"}[r["model_source"]]
    true_note = " (body only; the scan's cable left out)" if r["cropped"] else ""
    s3 = f"<tr><th>SAM 3D, fitted</th><td>{mm(r['sam3d_mm'])} mm</td></tr>" if r["sam3d_mm"] else ""
    h = c["holder"]
    ring = f", {c['cad_info']['hole_diameter_mm']:.1f} mm bore" if c["cad_info"].get("ring") else ""
    return f"""
<article class="obj" id="{r['name']}">
  <header class="obj-head">
    <h3>{NAMES[r['name']]}</h3>
    <span class="pill {kind}">{label}</span>
  </header>
  <p class="plan">Muse Spark chose <b>{r['route']}</b> and asked SAM 3.1 for “{html.escape(r['prompt'])}”. Model used: {used}.</p>
  <div class="shots four">
    <figure><img src="{img(r['images']['photo'])}" alt="One of the 16 photos of the {NAMES[r['name']].lower()}" loading="lazy"><figcaption>1 of 16 photos</figcaption></figure>
    <figure><img src="{img(r['images']['compare'])}" alt="Real object, our model and SAM 3D side by side" loading="lazy"><figcaption>Real · ours{' · SAM 3D' if r['sam3d_mm'] else ''}</figcaption></figure>
    <figure><img src="{img(r['images']['cad'])}" alt="The CAD model exported as STEP" loading="lazy"><figcaption>CAD: {CAD_KIND[c['cad_kind']].lower()}</figcaption></figure>
    <figure><img src="{img(r['images']['holder'])}" alt="The real object sitting in its parametric CAD holder" loading="lazy"><figcaption>Real object in its CAD holder</figcaption></figure>
  </div>
  <table class="nums">
    <tr><th>Real size{true_note}</th><td>{mm(r['true_mm'])} mm</td></tr>
    <tr><th>Built from the photos</th><td>{mm(r['hull_mm'])} mm</td></tr>
    {s3}
    <tr><th>Surface off (average · 90%)</th><td>{r['hull_surface_mean']:.2f} · {r['hull_surface_p90']:.2f} mm</td></tr>
    <tr><th>CAD (STEP)</th><td>{CAD_KIND[c['cad_kind']]}: {mm(c['cad_mm'])} mm{ring}, surface off {c['cad_surface_mean']:.2f} mm</td></tr>
    <tr><th>Cameras found · median error</th><td>{r['cameras']['posed']} of {r['cameras']['of']} · {r['cameras']['median_mm']:.2f} mm</td></tr>
    <tr><th>CAD holder: worst catch · median gap</th><td>{h['max_penetration_mm']:.2f} mm on {h['share_colliding_over_0.2mm'] * 100:.1f}% · {h['gap_below_rim_median_mm']:.2f} mm</td></tr>
  </table>
</article>"""


def page(rows, cad):
    cards = "\n".join(card(r, cad[r["name"]]) for r in rows)
    return f"""<title>Bevell 3D Scan Results</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700&family=Inter:wght@400;500;600&display=swap">
<style>
/* Layout: one reading column; each object is a card of three pictures over its measurements. Bevell's own look: near-black ground, the logo blue, Outfit and Inter. */
:root {{
  --bg: #f5f6f8; --card: #ffffff; --line: #e1e4ea; --fg: #14161a; --muted: #586070;
  --accent: #2445e0; --accent-fill: #395af6; --ok: #127a52; --ok-bg: #e3f4ec; --snug: #8a5a00; --snug-bg: #fbf0d9;
  --bad: #b3261e; --bad-bg: #fbe5e3; --chip-truth: #c9c4bb; --chip-ours: #395af6; --chip-sam: #8f74d6; --chip-holder: #e6e6ea; --chip-seat: #f08a4b;
  --display: "Outfit", "Avenir Next", "Segoe UI", sans-serif; --body: "Inter", -apple-system, "Segoe UI", sans-serif;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #14161a; --card: #1b1e24; --line: #2a2e36; --fg: #eceef2; --muted: #9aa1ad;
  --accent: #8095f9; --accent-fill: #395af6; --ok: #6fd3a5; --ok-bg: #133126; --snug: #f0c46a; --snug-bg: #33290f;
  --bad: #ff8a80; --bad-bg: #3a1714; color-scheme: dark }} }}
:root[data-theme="dark"] {{
  --bg: #14161a; --card: #1b1e24; --line: #2a2e36; --fg: #eceef2; --muted: #9aa1ad;
  --accent: #8095f9; --accent-fill: #395af6; --ok: #6fd3a5; --ok-bg: #133126; --snug: #f0c46a; --snug-bg: #33290f;
  --bad: #ff8a80; --bad-bg: #3a1714; color-scheme: dark }}
body {{ background: var(--bg); color: var(--fg); font: 15px/1.6 var(--body); }}
.wrap {{ max-width: 1080px; margin: 0 auto; padding-block: 40px 64px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); display: grid; gap: 40px; }}
h1, h2, h3 {{ font-family: var(--display); text-wrap: balance; margin: 0; line-height: 1.15; }}
h1 {{ font-size: clamp(30px, 5vw, 44px); font-weight: 700; }}
h2 {{ font-size: 24px; font-weight: 600; }}
h3 {{ font-size: 20px; font-weight: 600; }}
.eyebrow {{ font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--accent); font-weight: 600; }}
.lede {{ max-width: 66ch; color: var(--muted); margin: 0; }}
header.top {{ display: grid; gap: 14px; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 8px; }}
.stat {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; display: grid; gap: 2px; }}
.stat b {{ font-family: var(--display); font-size: 24px; font-weight: 600; font-variant-numeric: tabular-nums; }}
.stat span {{ color: var(--muted); font-size: 13px; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 8px 18px; font-size: 13px; color: var(--muted); }}
.legend i {{ display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; border: 1px solid var(--line); }}
section {{ display: grid; gap: 18px; }}
.obj {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 20px; display: grid; gap: 14px; min-width: 0; }}
.obj-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
.plan {{ margin: 0; color: var(--muted); font-size: 14px; }}
.plan b {{ color: var(--fg); font-weight: 600; }}
.pill {{ font-size: 13px; font-weight: 600; padding: 4px 10px; border-radius: 999px; }}
.pill.ok {{ color: var(--ok); background: var(--ok-bg); }}
.pill.snug {{ color: var(--snug); background: var(--snug-bg); }}
.pill.bad {{ color: var(--bad); background: var(--bad-bg); }}
.shots {{ display: grid; grid-template-columns: 0.75fr 1fr 1fr; gap: 10px; }}
.shots.two {{ grid-template-columns: 0.6fr 1fr; }}
.shots.four {{ grid-template-columns: 1fr 1fr; }}
figure {{ margin: 0; display: grid; gap: 6px; min-width: 0; }}
figure img {{ width: 100%; aspect-ratio: 16 / 10; object-fit: cover; border-radius: 10px; background: #eef0f3; display: block; }}
.shots.two figure:first-child img {{ aspect-ratio: 3 / 4; }}
figcaption {{ font-size: 12px; color: var(--muted); }}
.nums {{ width: 100%; border-collapse: collapse; font-size: 14px; font-variant-numeric: tabular-nums; }}
.nums th {{ text-align: left; font-weight: 500; color: var(--muted); padding: 7px 12px 7px 0; width: 46%; vertical-align: top; }}
.nums td {{ padding: 7px 0; }}
.nums tr + tr {{ border-top: 1px solid var(--line); }}
.findings {{ display: grid; gap: 12px; max-width: 72ch; }}
.findings p {{ margin: 0; }}
.cmp {{ overflow-x: auto; }}
.cmp table {{ border-collapse: collapse; min-width: 420px; font-variant-numeric: tabular-nums; font-size: 14px; }}
.cmp th, .cmp td {{ padding: 8px 14px 8px 0; text-align: left; border-bottom: 1px solid var(--line); }}
.cmp th {{ color: var(--muted); font-weight: 500; }}
.win {{ color: var(--accent); font-weight: 600; }}
.note {{ font-size: 13px; color: var(--muted); max-width: 72ch; margin: 0; }}
a {{ color: var(--accent); }}
@media (max-width: 720px) {{ .shots, .shots.two, .shots.four {{ grid-template-columns: 1fr; }} .shots.two figure:first-child img {{ aspect-ratio: 16 / 10; }} }}
</style>
<div class="wrap">
  <header class="top">
    <div class="eyebrow">Bevell 3D · Meta hackathon test run · 3 Nov 2026</div>
    <h1>Scan results</h1>
    <p class="lede">Five real scanned household objects, photographed on the capture sheet and rebuilt by the whole pipeline: Muse Spark plans, SAM 3.1 cuts the object out, the markers place every camera, SAM 3D adds a generated shape, and the result comes out as CAD (STEP) with a parametric holder to print. Every number below compares our output with the real object's scan.</p>
    <div class="stats">
      <div class="stat"><b>0.17–0.33 mm</b><span>median camera position error, per object</span></div>
      <div class="stat"><b>0.05%</b><span>focal length error, every set</span></div>
      <div class="stat"><b>≤ 1.5 mm</b><span>size error on every axis, 4 of 5 objects</span></div>
      <div class="stat"><b>4 of 5</b><span>real objects drop into their CAD holder</span></div>
    </div>
    <div class="legend">
      <span><i style="background:var(--chip-truth)"></i>Real object (the scan)</span>
      <span><i style="background:var(--chip-ours)"></i>Built from the photos</span>
      <span><i style="background:var(--chip-sam)"></i>SAM 3D, fitted to the photos</span>
      <span><i style="background:#8c97a6"></i>CAD model (STEP)</span>
      <span><i style="background:var(--chip-holder)"></i>Holder</span>
      <span><i style="background:var(--chip-seat)"></i>Real object in the holder</span>
    </div>
  </header>

  <section>
    <h2>Your AirPods, from the 2 Nov photos</h2>
    <article class="obj">
      <header class="obj-head"><h3>AirPods case</h3><span class="pill snug">Needs your calipers</span></header>
      <p class="plan">Real phone photos on creased plain paper, before the marker sheet. SAM 3D made the shape from one photo; the fit sized it against all eight.</p>
      <div class="shots two">
        <figure><img src="{img('airpods_photo.jpg')}" alt="The AirPods case on the paper, photo IMG_1746"><figcaption>IMG_1746, with SAM 3.1's outline used for SAM 3D</figcaption></figure>
        <figure><img src="{img('airpods_holder.jpg')}" alt="SAM 3D's AirPods case sitting in its generated holder"><figcaption>SAM 3D, fitted, in its holder</figcaption></figure>
      </div>
      <table class="nums">
        <tr><th>Fitted size</th><td>57.0 × 59.5 × 24.6 mm</td></tr>
        <tr><th>Agreement with the 8 photos</th><td>0.808 (photo build alone: 0.786)</td></tr>
        <tr><th>Caveat</th><td>The fit stretched one axis to its 15% limit, which points at the rough cameras from the paper's edges. Marker photos and a caliper reading will settle it.</td></tr>
      </table>
    </article>
  </section>

  <section>
    <h2>Benchmark objects</h2>
    {cards}
  </section>

  <section>
    <h2>The CAD outputs</h2>
    <div class="findings">
      <p><b>Round objects become editable CAD.</b> When Muse Spark calls an object round, its slices give a profile that is revolved into a real solid: the bottle came out 61.6 × 61.4 × 111.2 mm against 62.0 × 61.8 × 110.5, and the tape roll as a 117.2 mm ring with a straight 75.1 mm bore (a standard core is 76.2 mm). Edit the profile in any CAD package.</p>
      <p><b>Freeform objects are wrapped, not rebuilt.</b> Mario, the mug and the mouse come out as their mesh sewn into a closed STEP solid. It opens and measures in any CAD package but has no features to edit. SAM 3D's mouse is hollow inside, so it could not be lofted from slices.</p>
      <p><b>Every holder is a parametric CAD part.</b> Clearance 0.4 mm, wall 3 mm, floor 2 mm, pocket half the object's height up to 30 mm, and two 9 mm finger notches, all numbers in one place. Each holder also comes as STEP, STL and a top-view DXF of its pocket and outline. Cut round the object's outline from above with a flat floor, it fitted better than the earlier grid holder: the mouse's worst catch fell from 5.7 mm to 1.6 mm.</p>
    </div>
  </section>

  <section>
    <h2>What we learned</h2>
    <div class="cmp"><table>
      <tr><th>Surface off, average</th><th>Built from the photos</th><th>SAM 3D, fitted</th></tr>
      <tr><td>Mario figure</td><td class="win">0.91 mm</td><td>1.42 mm</td></tr>
      <tr><td>Mug with handle</td><td>3.57 mm</td><td class="win">2.98 mm</td></tr>
      <tr><td>White mouse</td><td>5.13 mm</td><td class="win">1.58 mm</td></tr>
    </table></div>
    <div class="findings">
      <p><b>SAM 3D earns its place on some objects.</b> It sees what photos can't carve: the inside of the mug, the hole in its handle, and the edges of a white mouse that the cut-outs missed. The photos alone win on Mario. The pipeline now keeps SAM 3D's shape when it agrees with the photos within 0.08 of the photo build.</p>
      <p><b>Contrast decides the holder.</b> A white object on the white sheet gets cut-outs that are too small, so the model and the holder come out too small. Fixes to try: print the sheet's centre in mid grey, have Muse Spark warn about low contrast, and widen the clearance when the photos disagree.</p>
      <p><b>The holder trusts the photos when they agree.</b> When the cut-outs agree with each other (0.95 or better), the holder is cut round the photo build, which is an outer bound. That fitted every such object here: with the CAD holders the worst catch was 0.34 mm, on 0.1% of Mario's surface.</p>
      <p><b>Round objects.</b> The round-profile route first broke on the tape's hole and came out 6 mm narrow on the bottle. Both are fixed. With 16 good photos the photo build is still closer, and the pipeline picks it automatically.</p>
    </div>
  </section>

  <section>
    <h2>How this was tested</h2>
    <p class="note">Objects from Google Scanned Objects (Google Research, CC BY 4.0), true size and textured. Each was rendered in Blender on the capture sheet: 16 photos at 2016 px, six from 45° up, eight from 10° up and two from above, as the capture guide asks. The pipeline ran unchanged, with real Muse Spark and SAM 3.1 calls over the Meta Model API and SAM 3D Objects on a Modal L40S. Surface error is the average distance from the real surface to ours; the holder check sits the real object in the printed holder and measures where it would catch. These are rendered photos, so real phone photos will be a little harsher. The mug's surface number includes its inside, which no photo of the outside can reach.</p>
  </section>
</div>
"""


if __name__ == "__main__":
    rows = json.load(open(f"{R}/results.json"))
    cad = {c["name"]: c for c in json.load(open(f"{R}/cad.json"))}
    open(sys.argv[1], "w").write(page(rows, cad))
    print("wrote", sys.argv[1])
