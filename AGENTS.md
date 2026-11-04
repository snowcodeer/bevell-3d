# Bevell 3D: handover for agents

Natalie Chan's entry to the **Meta Global AI Developer Hackathon** (Cerebral Valley, remote,
$1M pool). Photos of an object on a printed marker sheet in; a true-to-size 3D model and a
3D-printable holder for it out. Startup track. Last updated 3 Nov 2026.

## Deadline and what must be handed in

- **Due Wed 4 Nov 2026, 9:00 PM ET = 02:00 UK, Thu 5 Nov.** Late entries are not judged.
- Submitted on the Cerebral Valley platform (event page, "Submit Project"). **Natalie submits;
  an agent may fill the form but never presses Submit.** Fields seen on 3 Nov:
  team name (Bevell), team members, track (Startups Track), problem statement (Build for Your
  World / Push the Frontier; ours is Push the Frontier: manufacturing), optional X post link
  for Most Viral, project description, **public GitHub repository**, **3-minute demo video**,
  "Describe your use of Meta products", "Why are Meta's models important to your solution?",
  optional partner feedback, two Meta Model API survey questions, two 0-5 recommendation
  scores (Model API, Muse Code), biggest obstacle (multiple choice), and a consent that Meta
  and Cerebral Valley may publish the submission.
- Rules (participant guide, cerebralvalley.ai/e/meta-ai-developer-hackathon/details, logged in):
  - The repository must be public.
  - Only work built during the event (27 Oct to 4 Nov) may be shown, and it must be clearly
    identified. Startups may build on an existing product, so this repo talks to Bevell only
    through its public API and Bevell's own code is not here.
  - The 3-minute video shows only new work.
  - It must use Meta's models: Muse Spark, Muse Wonder, Muse Image, Muse Voice Transcribe and
    SAM 3.1 through the Meta Model API, or the open-weight Muse Glimmer and Muse Spark Open.
- Judging rubric: impact 30%, use of Meta tooling 25%, demo 25%, technical depth 20%.
  - Bonus prizes:
    - $20K: most engagement on X by 8 Nov.
    - $10K: built on Muse Spark Open or Muse Glimmer, served on your own or a partner's
      hardware (Modal and Baseten count).
    - $10K: community vote.
    - $5K: best agentic use.
- Avoid anything political or involving war in the demo (an "anti-project" in the rules).

## Rules for agents working here

- Never type passwords, 2FA codes, API keys, tokens or card details, and never create
  accounts. Natalie does those. Never print a secret.
- **Never push to GitHub, make the repo public, post, or submit without Natalie's yes.** The
  repo is local only until she says.
- **Secrets:**
  - The Meta key lives in a `.env` file outside the repo (`MODEL_API_KEY`,
    `MODEL_API_BASE=https://api.meta.ai/v1`); load it with
    `set -a; source path/to/meta.env; set +a`.
  - The Modal token is in `~/.modal.toml` (workspace `nataliechan1963`).
  - The Hugging Face token lives only in the Modal secret `huggingface` (key `HF_TOKEN`).
- Commits have no Co-Authored-By or AI attribution lines. Writing for Natalie is lean, with
  no em dashes.
- Every dimension comes from the photos and the sheet. Models make choices (prompt, route) or
  shapes that are then fitted; they never supply a number in mm.

## Accounts and credits (as of 3 Nov)

| What | State |
|---|---|
| Meta Model API, dev.meta.ai | Key "Bevell hackathon". Models: muse-spark-1.3 (reasoning, vision, structured output; give it max_tokens room), sam-3.1, muse-wonder-1.0 (text agent model), muse-image-1.0. Natalie says the $150 credits are claimed |
| Modal, workspace `nataliechan1963` | A spending limit is set, which unlocks $30 a month free. $100 hackathon credits requested 3 Nov (selected teams only) |
| Baseten | $100 + 2M TPM for Muse Spark Open requested 3 Nov (no account needed; email if chosen) |
| Hugging Face `facebook/sam-3d-objects` | Gated; **access approved 3 Nov**. Read token `modal-sam3d` made 3 Nov and saved by Natalie as the Modal secret `huggingface` (`HF_TOKEN`); the weights download worked |
| Fireworks | Not requested (needs an account first) |

## How it works

```
photos (HEIC/JPEG) on the capture sheet
  -> photos.prepare      upright, 1536 px max, one pixel frame for everything
  -> planner.plan        Muse Spark: SAM 3.1 prompt, route (flat/revolved/freeform), photo issues
  -> markers.solve       ArUco corners -> shared focal length (calibrateCamera) + PnP per photo
  -> scan.masks_for      SAM 3.1 over the Meta Model API, cached in <out>/masks.pkl
  -> hull.visual_hull    voxel carve over the sheet's white area, marching cubes, Taubin
  -> revolve.revolved    route 'revolved': inscribed circle per hull slice -> profile -> revolve
  -> modal_app/sam3d.py  route 'freeform': SAM 3D Objects on a 48 GB GPU, best photo + mask -> GLB
  -> fit.fit             up axis + turn search, then scale/turn/tilt/position on silhouette IoU,
                          optional per-axis stretch up to 15%
  -> holder.make_holder  pocket = everything above the underside inside the footprint, + 0.4 mm
  -> render / tools/blender_render.py
```

- World frame (`sheet.py`): mm, origin at the page's printed top-left, X along the long edge,
  Y = 210 - page y, Z up out of the paper. The object sits at Z >= 0. The white area inside
  the markers is X 31..266, Y 31..179.
- Capture sheet: `assets/bevell_capture_sheet.pdf` (also `~/Downloads/bevell_capture_sheet.pdf`).
  It has 22 DICT_4X4_50 markers of 22 mm, laid out as in `assets/capture_sheet_layout.json`.
  Checked on 3 Nov: all 22 markers in the PDF sit within 0.11 mm of the layout.
- `carve.py`, `refine.py`, `silrefine.py` and `flat.py` are the 2 Nov prototype, which used the
  A4 sheet's edges instead of markers. They are kept for the plain-paper fallback, but the
  marker path (`scan.py`) replaces them. `flat.py` still uses the old path.

## Commands

```bash
cd ~/Projects/bevell-3d
.venv/bin/python -m pytest -q tests/ -p no:warnings      # 6 tests, ~10 s, no network
set -a; source path/to/meta.env; set +a
.venv/bin/python -m bevell3d.planner photo1.jpg photo2.jpg   # Muse Spark plan
.venv/bin/python -m bevell3d.scan --prompt "dark blue earbuds case" --out out/x photos/*.HEIC
.venv/bin/python -m bevell3d.run --out out/x photos/*.HEIC   # everything; --no-sam3d to skip the GPU
HF_SECRET=0 .venv/bin/modal run modal_app/sam3d.py::check_image   # build + import test, no weights
.venv/bin/modal deploy modal_app/sam3d.py                        # needed before run.py can call it
/Applications/Blender.app/Contents/MacOS/Blender -b -P tools/blender_render.py -- \
    --out out/x/holder_render.png --part out/x/holder.stl:dcdce0 --part out/x/model.stl:395af6
```

The venv is `uv`-made, Python 3.12, with pins in `requirements.txt`. Blender 5.0.1 is
installed and its render engine is EEVEE.

## Measured so far

- **Markers (synthetic photos of the real layout):**
  - 13 cameras at 45°, 20° and 85° above the table: the focal length came back within 0.02%
    (1266.2 against 1266 px), and every camera within 0.3 mm.
  - With 8° low shots, at least 10 markers were still found in every photo. At 5°, half the
    low photos failed.
- **Visual hull:**
  - It is an outer bound. A box comes back about 1.5 mm wider on each side, which is normal
    for this method with perspective photos.
  - Its height is far too tall without low photos. With a 20° ring, a 21.2 mm box came out
    28.1 mm; with a 12° ring 24.7, with 8° 23.2.
  - That is why the 2 Nov AirPods came out about twice as tall as they are.
- **Fit:**
  - An L bracket handed over Y-up, at unit size and turned 37° came back at 59.6 × 40.1 ×
    30.0 mm (true 60 × 40 × 30), mean IoU 0.966 at quarter resolution.
  - A copy 10% too tall and 6% too narrow was stretched back to within 1 mm.
- **Holder:**
  - Test box and bottle: 0.4 to 0.5 mm gap all round (5th to 95th percentile 0.14 to 0.47 on
    the box), no overlap, watertight.
  - About 2 s to build, decimated to 200k faces.
- **Planner (2 Nov photos):**
  - It called the medal flat, the earbuds case freeform, and the bottle freeform (it is
    flattened, with a carabiner, which is why its hull came out thin).
  - It flagged the creases, shadows, hands in shot and missing low shots.
- **2 Nov prototype (creased A4, no markers, no low shots):**
  - The medal measured 50.0 mm in both photos.
  - The AirPods came out 52 × 48 × 40 mm, far too tall.
  - Copies are in `out/prototype-2nov/` (photos, masks, meshes); the original HEICs are
    `~/Downloads/IMG_1739..1755.HEIC`.
  - IMG_1739-1740 are the medal, 1741-1748 the AirPods, 1749-1755 the bottle.
  - The cached masks are 1536 × 1152 in the photo's *stored* frame (EXIF orientation 6, not
    applied). To pair a photo with its mask, convert the HEIC with `sips`, open it with
    Pillow without `exif_transpose`, and scale it to 1536. `out/prototype-2nov/small/` is
    900 px and also un-rotated.

## Benchmark (3 Nov): rendered Google Scanned Objects

`tools/render_bench.py` photographs a scanned object (true size, textured, CC BY 4.0, from
Gazebo Fuel's GoogleResearch collection) on the capture sheet in Blender: 16 photos in a 45°
ring, a 10° ring and from above, 2016 px. `tools/bench_eval.py` runs `bevell3d.run` on them,
with real Muse Spark and SAM 3.1 calls and SAM 3D on Modal, and scores against the true mesh.
The models are in `out/bench/gso/`, and each object's results are in `out/bench/<object>/full/`.

| Object | Cameras (median error) | True size, mm | Our model, mm | Surface off, mean / p90 | Holder |
|---|---|---|---|---|---|
| Mario figure | 0.24 mm | 72.2 × 47.8 × 102.4 | 70.7 × 46.3 × 102.6 (hull) | 0.91 / 1.86 mm | fits; 0.74 mm catch on 0.5% |
| Mug with handle | 0.33 mm | 165.7 × 125.5 × 94.8 | 165.4 × 125.1 × 95.2 (hull) | 3.57 / 7.61 (inside of the mug can't be carved) | fits; 0.23 mm worst |
| Vitamin bottle | 0.17 mm | 62.0 × 61.8 × 110.5 | 63.4 × 61.6 × 111.2 (hull) | 1.44 / 3.87 mm | fits; 0.31 mm worst |
| Tape roll | 0.32 mm | 118.1 × 117.0 × 50.2 | 118.7 × 116.9 × 51.3 (hull) | 0.98 / 1.65 mm | fits; 1.2 mm catch on 1.9% |
| White mouse (body) | 0.33 mm | about 124 × 65 × 40 | 124.3 × 66.0 × 38.0 (SAM 3D) | 1.58 / 3.24 (hull 5.13) | **too tight**: masks missed white-on-white edges |

- **Lens:** recovered within 0.05% every time. 15 or 16 of 16 photos were posed.
- **SAM 3D against the hull, on the true surface:**
  - Mario: hull 0.91, SAM 3D 1.42 mm mean.
  - Mug: SAM 3D 2.98, hull 3.57. SAM 3D models the hollow and the handle hole.
  - Mouse: SAM 3D 1.58, hull 5.13.
  - So `KEEP_MARGIN` is now 0.08. The holder is cut round the hull when its agreement is
    0.95 or more, and round the chosen model otherwise (`HULL_HOLDER_AGREEMENT`).
- **Revolved route:** it broke on the tape's hole (fixed: slices are filled) and was 6 mm too
  narrow on the bottle (fixed: each slice's own inscribed radius, centroid axis). With 16
  good photos the hull is still nearer the truth (bottle 1.47 against 2.83 mm), and the
  agreement check picks the hull.
- **The mouse cable:** the scan includes a coiled cable that SAM 3.1 rightly left out.
  `--crop` scores only the part of the true object over the model's footprint.
- **Biggest lesson: contrast.** A white object on the white sheet gets masks that are too
  tight, so everything built from them is too small, and the holder with it. Ideas:
  - print the sheet's centre in a mid grey;
  - have the planner flag low contrast and ask for a coloured backing;
  - widen the clearance when the hull's agreement is below 0.9.
- **Memory:** five runs at once ran the 16 GB Mac out of memory. Run benchmarks one after
  another. The holder grid now scales with size, and a 166 mm mug peaks at about 1.1 GB.

## CAD (3 Nov)

`bevell3d/cad.py`, called by `run.py`. CadQuery 2.8 on OCP 7.9 (`requirements.txt`).
- **Model to STEP, tried in order:**
  1. Revolve, when every middle slice is one round loop about one axis. A ring gets a straight
     bore at the median measured radius.
  2. Loft through 14 slice outlines resampled to 40 points from the same bearing.
  3. The mesh sewn into a closed solid, never more than about 4,000 triangles; 142,000 took
     four minutes.
  - Each candidate must match the mesh's volume within 8 to 10%.
  - Muse Spark's "revolved" lowers the roundness bar from 0.92 to 0.8; the volume check
    still decides.
- **Holder:** `holder_cad` is parametric (`HolderParams`: clearance 0.4, wall 3, floor 2,
  half height up to 30 mm). It writes `holder.step`, `holder.stl`, `holder.3mf` and
  `holder_top.dxf` (layers POCKET and OUTLINE). The voxel nest that follows the underside is
  kept as `holder_nest.stl`. Rebuilt 3 Nov after Natalie found the rim lumpy:
  - **Outline** (`smooth_outline`): a footprint within 1 mm or 3.5% of a circle is a true
    circle enclosing the whole trace (the bottle's hull is ±0.7 mm off round; Mario, the
    nearest thing that is not, 5 mm). Round holders are looser for it: the bottle's median gap
    went from 0.9 to 1.6 mm, as the tape's always was. Anything else is a smoothing spline
    (0.5 mm; 0.3 left creases on the bottle) fitted as an upper envelope: points that
    poke through pull the curve out only where they are, so a box's flat sides keep 0.4 mm.
    Beside a perfectly sharp corner the curve bulges to about 1 mm; clipping it to the trace
    left kinks that broke every fillet on Mario and the mug, and so did spacing the spline's
    points by bend. Both were tried and reverted on 3 Nov.
  - The pocket's inward corners are closed by 2 mm and the outside's by 3.5 mm, because a
    chamfer or fillet cannot pass a bend tighter than itself.
  - **Every check runs on the curve CadQuery cuts**, sampled edge by edge over each edge's own
    parameter range (`_edge_points`). Asked by length, CadQuery measures the arc again for
    every point and took minutes; asked by raw parameter, a spline's runs over its chord
    length, not 0 to 1.
  - **Edge treatments**, each reported in `info["dfm"]`: 0.8 mm lead-in at the pocket mouth
    and 0.4 mm chamfer on the foot against elephant's foot, both built as ruled lofts at 45°
    (`_lead_in_cutter`, `_foot_cutter`) because OpenCascade's own chamfer on Mario's pocket
    ran for minutes and failed on its foot; 1.36 mm fillet on the outer rim; then U-shaped
    finger notches (a horizontal cylinder through the
    wall) with a 0.8 mm fillet, else 0.4, else a 0.4 chamfer. Rim and foot are treated
    while each is still one closed loop; with the notches cut first they failed on two of five.
  - **`holder_cad_safe`** runs it in a spawned child. A notch fillet segfaulted OpenCascade on
    a box, which would take the web server down. On a crash or a hang it retries without the
    notch treatments, then without any (`_FALLBACKS`); the result says which.
  - `to_mesh` welds vertices closer than 0.05 mm: the lead-in left 0.01 mm edges unshared.
  - `to_mesh` hands back the mesh a sewn solid was made from (`_source_mesh`): OpenCascade
    took 140 to 190 s to mesh Mario's 3,000 flat faces again, most of the 319 s the CAD step
    took in the web app.
- **Benchmark (`tools/cad_bench.py`, `out/results/cad.json`):**
  - Bottle: revolved, 61.6 × 61.4 × 111.2 mm (true 62.0 × 61.8 × 110.5).
  - Tape: revolved ring, 117.2 mm with a 75.1 mm bore (a standard core is 76.2).
  - Mario, mug, mouse: sewn STEP solids. SAM 3D's mouse is hollow between 17 and 27 mm up,
    so slicing cannot loft it.
  - CAD holders: 4 of 5 with no catch over 0.34 mm. The mouse's worst catch is 1.6 mm on 6%,
    against the voxel nest's 5.7 mm.
- **Results page:** `tools/results_renders.py` then `tools/results_page.py <out.html>`.
  Published privately at https://claude.ai/artifact/MxX5ZCnRBivYJQznJ3uzmS.

## Deployed (4 Nov): https://nataliechan1963--bevell-3d-web.us-east.modal.run

- `modal_app/web.py` (Modal app `bevell-3d`): the same FastAPI server, one container (4 CPU,
  8 GiB), Blender 5.0.1 for the NURBS step, SAM 3D called on `bevell-sam3d` as locally.
- Scans live in the Volume `bevell-3d-scans`, committed every 15 s. The eight examples
  (`SHOWN` in `tools/seed_examples.py`) are put there with
  `modal volume put --force bevell-3d-scans out/scans/example-<name> /example-<name>` after
  `python -m tools.seed_examples`. **Then stop the web container** (`modal container list`,
  `modal container stop -y <id>`): a redeploy that changes no code keeps the warm container,
  whose view of the volume predates the upload, so new files stay invisible (4 Nov).
- Secrets: `bevell-3d-meta` (the Meta key, from `.env.meta`) and `bevell-3d-access`
  (`BEVELL3D_PASSCODE`). **The passcode is not written in this repo**; Natalie has it. A
  scan or an agent run needs it (header `x-passcode`, a field on the photo check screen), and
  there are 50 runs a day (UTC, `/scans/_usage.json`), then 429.
- Checked through the deployed app with `tools.webapp_e2e --passcode`: the bottle in 129 s,
  Mario in 221 s with SAM 3D and a NURBS STEP, 12 of 12 files open each time.
- The examples' freeform models are NURBS (Mario, the mug, the clock); the mouse's
  QuadriFlow left a hole at every density tried, so it keeps its triangle STEP.

## Web app (3 Nov)

`webapp/`: a FastAPI server plus one page, styled like Bevell and built mobile first.
- **Run it:** `set -a; source path/to/meta.env; set +a; .venv/bin/uvicorn webapp.server:app --port 8300`.
- **The page** is one app-like flow, one screen per step, routed by hash so the back gesture
  works: start → sheet checklist → place → guided capture → review → making → result →
  print.
  - On a phone, "Take photo N" opens the camera and a dial shows where to stand next: 6 at
    45°, 8 low, 2 from above.
  - The result is a three.js viewer (model, holder, or the model in its holder).
  - Print offers "Open in Bambu Studio" (`bambustudio://open?file=<url of holder.3mf>`,
    the community-documented scheme MakerWorld uses; it needs a 3MF, not an STL). On a
    phone it saves the 3MF instead.
- **Copy:** Natalie asked for as little text as possible (3 Nov). Keep it that way.
- **Server:**
  - Scans live in `out/scans/<id>/` (uploads, `result/`, `status.json`); the page polls
    `/api/scans/<id>`. One scan runs at a time per process.
  - `tools/seed_examples.py` copies benchmark results in as `example-<name>`.
- **Not deployed yet:** to use it from a phone, run it on `--host 0.0.0.0` on the same
  Wi-Fi, or deploy it to Modal (the next step, for the "holds up in production" judging).
- **Timings:** `run.py` records `timings_s`.
  - Mario: 143 s in all (plan 10, masks 11 with four SAM 3.1 calls at a time, hull 5,
    SAM 3D 67, fit 26, CAD and holder 14).
  - Bottle: 59 s in all (revolved, no SAM 3D).

## Prismatic parts, scan checks and the robot fixture (4 Nov)

- **Prismatic route** (`cad.prismatic_cad`, tried after the revolve): the solid sliced every
  millimetre, slices grouped into at most 4 levels whose outline does not change (a run under
  3% of the height is a transition and joins its neighbours), each level a polygon extruded to
  its height, round holes as true circles, a hole through several levels as one feature. Kept
  only when it differs from the solid by under 10% of the volume. It writes `model_tree.json`
  and `model_fusion.zip` (level heights and hole diameters as parameters), and the result
  screen says the CAD is already editable.
  - Designed test parts (`tools/make_parts.py`): bracket, L-bracket, gear, sloped stand. On
    their exact meshes the bracket is 2 levels and 3 holes, the gear 2 levels and a bore, both
    within 0.2% by volume; the stand is refused.
  - From the bracket's scan: 2 levels (9.3 and 20.7 mm, true 8 and 22) and 3 holes, 0.93 mm
    from the true surface, 63.6 cm3 (true 65.2). Tuning the levels against the photos was tried
    (1.16 mm, but 11 minutes and still four levels) and left out.
  - On hulls the route is often refused: a visual hull cannot carve beside a step, so slices
    taper. Real prismatic scans then go to NURBS, and "Make it editable" gives the designer's
    tree (the agent read the bracket as a flange, an offset tower, a bore and two holes).
- **Shells** (`cad.solidify`): SAM 3D can return walls open underneath with slits (the mouse:
  31.9 cm3 of a 186 cm3 solid). With the sheet as a floor and gaps to 6.5 mm closed, enclosed
  space is filled, only when that cavity is 30% of the mesh or more (mouse 2.26, every other
  object 0.0). The runner and recad fill before writing model.stl.
- **Scan checks** (`scan.py`):
  - `object_mask` joins SAM 3.1 instances that touch the best one: the letter holder came back
    as two, and one photo's mask without the back compartment cut 26 mm off the hull.
  - `check_coverage` refuses photos all taken from one spot (within 25 degrees) before any
    masks; `check_bounded` refuses a shape that runs off the top or reaches the squares.
  - The carve reaches 250 mm and keeps only what rests on the sheet (`hull.on_sheet`, thin
    necks joined): the 160 mm ceiling cut the 162 mm clock, and a higher ceiling alone grew a
    floating tower over every object.
  - An unreadable photo is left out and named in the report (`photos/unreadable.json`).
- **Robot fixture** (`bevell3d/fixture.py`, every scan): finger reliefs on the grasp's squeeze
  axis sized from the SO-101 pads, a tab with a 30 mm recess for a printed ArUco tag (4x4, id
  40; `tag.pdf` marks the edge to stick towards the part), and `fixture.json` with the pick in
  the marker's own frame. `tools/pick_preview.py` finds the tag in a camera image and draws the
  pick. Tests: valid fixture, the tag found at its size, the pose 300 mm away within 3 mm.
- **recad:** `python -m bevell3d.run --recad --out <scan>` makes a finished scan's outputs
  again with today's code (CAD, holders, pads, fixture), no new photos or model calls.
- **User tests** (`tools/user_tests.py`, real pipeline): minimum 8 photos, one side only,
  blurred, dark, 640 px, 48 MP, rotated by EXIF, PNG and HEIC all come out within 2.5 mm;
  sixteen copies of one photo and photos with no sheet are refused with what to do; a broken
  photo is skipped. API tests (`tests/test_webapp.py`, 23) cover the passcode, the cap, photo
  limits, file types, ids and path traversal.
- **Demo:** `docs/DEMO.md` (script and shots), `docs/SUBMISSION.md` (form answers).

## Smooth NURBS for freeform scans (4 Nov)

- `bevell3d/nurbs.py`: a freeform model's STEP is smooth Bezier patches, not flat triangles.
  QuadriFlow (in a background Blender, `BLENDER` overrides the path) quad-remeshes the scan,
  about one quad per 10 mm² (800 to 4,000); each quad becomes a bicubic patch approximating
  the Catmull-Clark surface (Loop and Schaefer 2008); the cage is moved so the surface passes
  through the scan (without it Mario came out 4% small); the patches share their boundaries
  and sew into one solid.
- Measured: Mario 1,464 patches, 0.06 mm from its scan, 0.93 mm from the true figure (the
  scan itself is 0.92); the clock 3,121 patches, 0.11 mm from its scan but 3.04 mm from the
  truth against the scan's 2.62 (thin parts soften). Fusion opens Mario as one solid in 2.6 s.
- QuadriFlow needs a closed manifold mesh: a hollow SAM 3D shell goes through `clean_body`;
  over 120,000 faces it is voxel-remeshed inside Blender first (decimating in trimesh broke
  manifoldness and QuadriFlow failed on all three objects); at some densities it leaves a hole
  (the mouse at 3,000), so it retries at 60% and 35%.
- `run.py` uses it when `to_cad` falls back to a mesh (kind `nurbs`, "Smooth NURBS" in the
  web app), and keeps the triangle STEP if it fails. It adds 60 to 135 s. A deploy needs
  Blender in the image.

## CAD agent and feature tree (3 Nov)

- **`bevell3d/feature_tree.py`** is the CAD-neutral model. It holds named parameters, and
  steps (revolve, extrude, loft, sweep, shell, fillet, chamfer) whose sizes are expressions
  in those parameters.
  - Expressions are parsed by an AST whitelist and never executed.
  - `to_cadquery` builds the tree for checking.
  - `write_fusion_script` writes a Fusion 360 script folder. Running it opens a new
    parametric design with the parameters as user parameters and each step as a named
    timeline feature.
  - Run the script in Fusion from Utilities > Add-Ins > Scripts and Add-Ins.
  - Its `build(ui, close)` runs without dialogs and returns a report: errors per step, the
    timeline, the parameters and each body's volume and size. `run()` calls it and shows a
    message only when a step failed.
  - Fixed 3 Nov after the first run in Fusion failed: lengths were written as `x * 1 mm`,
    which Fusion read as mm squared, and the revolve used a separate axis line. It now
    revolves about the profile's own edge on x = 0.
  - The bottle's copy is installed at `~/Library/Application Support/Autodesk/Autodesk
    Fusion 360/API/Scripts/BevellBottle` (the version from before the fixes).
- **Testing it in Fusion:** `fusion_bridge/BevellBridge` is an add-in that serves
  `127.0.0.1:47822` inside Fusion and runs a script's `build()` on the main thread. It is
  installed in Fusion's `API/AddIns` folder; start it once from Utilities > Add-Ins >
  Scripts and Add-Ins > Add-Ins > BevellBridge > Run (`curl 127.0.0.1:47822/` answers when
  it is up). Then `.venv/bin/python -m tools.fusion_e2e` builds six trees (bottle and mug
  by hand, a loft with a cut and chamfer, a block with an ellipse boss, a polygon cut and a
  fillet, and the agent's bottle and mouse) in Fusion and in CadQuery, and fails on a step
  error or more than 3% volume or 0.5 mm size apart. Results in `out/fusion_e2e.json`.
  - **3 Nov, Fusion 2706.1.17: all six pass**, volume within 0.6% and size within 0.44 mm of
    CadQuery, one solid each. Sketches and planes are named after their step ("cap sketch",
    "cap plane"), parameters Fusion reads as units get `_mm` (`l` to `l_mm`).
  - If every sketch fails with a missing `.../Resources/sketch/Sketch_feature` folder, Fusion
    is running from a half-downloaded update: quit it fully and reopen. That is what broke the
    first BevellBottle run.
  - **Lofts must match Fusion's.** CadQuery lofts are built section by section on their own
    planes (a chained `at` used to move every later section), isoparametrically
    (`_loft`; OpenCascade's default made the mouse 3% fuller than Fusion builds it), and a
    `spline` shape puts point k at parameter k/n (by chord length the sections twisted and
    the loft came out 6% thin). Seven cases pass, the seventh a spline loft with a cut.
  - `write_fusion_zip` rewrites a scan's script and `agent_fusion.zip` from its
    `agent_tree.json`; `seed_examples` uses it, so the examples carry today's script.
- **`bevell3d/agent_cad.py`** (`python -m bevell3d.agent_cad <scan dir> --rounds 2`):
  1. Muse Spark writes the tree; `--mode code` asks for CadQuery code instead.
  2. A sandboxed worker builds it, and Nelder-Mead tunes the parameters and placement
     (160 builds, 1 to 6 minutes) on silhouette IoU at quarter resolution.
  3. Muse Spark gets a per-photo mismatch image (red: missing, cyan: extra) and revises.
  4. Outputs: `agent_tree.json`, `agent_fusion.zip`, `agent_model.step` and `.stl`, and
     `agent_report.json`.
- **Results on the rendered benchmark:**
  - Bottle, tree: 0.968 IoU. Code: 0.971, 1.21 mm mean from the true surface, the closest of
    any model.
  - Mug, code: body, foot, hollow, rim fillet and swept handle; 160.8 × 122.5 × 94.2 mm
    (true 165.7 × 125.5 × 94.8), 0.958 IoU against the hull's 0.976.
    - 2.09 mm mean from the true surface, the closest of any method; it models the inside
      (SAM 3D 2.98, hull 3.57).
  - Mouse, tree: a lofted dome with a scroll recess, 125.0 × 71.0 × 38.4 mm, 2.6 mm mean;
    it is held back by the white-on-white masks (SAM 3D fitted: 1.58).
- **The legacy Fusion plugin** is in `a separate private repo`: the BevellMCP
  add-in, JSON-RPC on `localhost:47821`, with sketch, revolve, loft, sweep, fillet and
  `execute_script` tools. A live "send to Fusion" could post the generated script to
  `execute_script` when the add-in is running. Not wired up yet.

## Gotchas already paid for

- `cv2.fillPoly` with many triangles fills by even-odd and holes the outline; `project.silhouette`
  draws triangle by triangle. The 2 Nov prototype's IoU numbers used fillPoly and read low.
- OpenCV applies EXIF rotation and Pillow does not; `photos.prepare` bakes it in once.
- SAM 3.1 masks arrive as a crop inside their bounds, and large ones arrive downsampled:
  `sam_client` pastes them at the bounds and resizes them. Parse the stream with
  `meta-sam-parser` and `await parsed.final_result()`.
- **SAM 3D's environment:**
  - Its setup lists `pypi.ngc.nvidia.com`, which no longer resolves, and every package retried
    5 times. Only the PyTorch cu121 index is used now.
  - pytorch3d, flash-attn and the inference requirements install with `--no-build-isolation`
    against torch 2.5.1.
  - SAM 3D needs at least 32 GB of GPU memory, so it runs on an L40S (48 GB).
  - Its output dict carries `glb` (a trimesh) when it decodes a mesh. The pose
    (`rotation`, `translation`, `scale`) is in the camera frame and is not used; `fit` does
    the placing.
- Hunyuan3D's licence excludes the UK, so it is not an option. TRELLIS (MIT) is the ungated
  fallback if SAM 3D will not build.
- The holder grows the pocket by whole grid columns (`ceil(clearance / pitch)`), with each
  column sampled at its centre. Fractional radii and corner-indexed columns left one side
  with no gap.

## Status and next steps

**Done (committed, local only):**
- markers (found at full resolution, reported in the 1536 px working frame), scan, hull, fit,
  holder (walls Taubin-smoothed), planner, revolved route, runner, Blender render;
- tests: 8, all passing, including an end-to-end scan from synthetic photo files;
- SAM 3D weights (13 GB, mesh decoder included) are in the Modal Volume
  `bevell-sam3d-weights` at `/weights/checkpoints/hf`, copied by `modal_app/sam3d_weights.py`;
- the `huggingface` Modal secret exists (made 3 Nov); a spending limit is set on Modal.
- **Revolved route:** on a synthetic waisted vase the axis came back exact and the diameter
  within 0.2 mm (mean 0.11) from 5 to 90 mm up. `run.py` uses it when the plan says
  revolved, and keeps it only if it agrees with the photos as well as the hull.

**SAM 3D is deployed** as `bevell-sam3d` on Modal: about 2 min 20 s for a cold call, about
60 to 90 s warm. The image took four fixes, all in `modal_app/sam3d.py`:
- the dead NVIDIA index;
- `nvidia-pyindex`, dropped from SAM 3D's requirements.txt in the build;
- gcc instead of the clang++ that Modal's Python asks for;
- `LIDRA_SKIP_INIT` and the CUDA paths the notebook loader expects.

A rebuild from scratch takes about 40 minutes, because it compiles pytorch3d for four GPU
architectures.

**Bevell integration plan:** `the private Bevell repo`, in the
private Bevell repo because it names Bevell internals.

**Open, roughly in order:**

1. **SAM 3D on the 2 Nov AirPods (done 3 Nov):** fitted 57.0 × 59.5 × 24.6 mm, agreement 0.808 against the hull's 0.786, stretch at its limit (1.15, 0.869), which suggests the old A4-edge cameras. Render: `out/sam3d_test/holder_render.png`. To redo it, run `.venv/bin/python -m tools.sam3d_prototype 1746`. It sends the upright photo
     and mask in `out/sam3d_test/` (made from the 2 Nov HEIC and the cached SAM 3.1 mask, and
     checked by overlay), fits the result to the eight 2 Nov photos, and builds a holder. The
     2 Nov cameras come from the old A4-edge path, so expect a looser fit than with markers.
   - If the build fails, read the step that failed in the log; every step after
     `requirements.txt` compiles against torch 2.5.1 cu121.
   - On the case's size: in IMG_1746 the case looks to be standing upright, not lying flat.
     The earlier guess that it should be about 24 mm tall may be wrong. Ask Natalie for
     caliper measurements.
2. **Reshoot (Natalie):**
   - Print the sheet at 100%, check a marker measures 22 mm, tape it flat.
   - For each object take 12 to 16 photos: a ring at about 45°, a ring at about 10°, and two
     from straight above.
   - Measure each object with calipers.
   - Objects: the AirPods case, a round bottle or cup (for the revolved route), and a tool
     worth a holder.
   - Run `bevell3d.run` on each set.
3. **Flat route on markers:** port `flat.py`, and optionally send the rectified top view to
   Bevell's public API for a DXF. That ties the hackathon work to the product without
   copying Bevell code.
4. **Test print** of a holder, if Natalie has a printer (still unconfirmed).
5. **"Holds up in production":** a small upload page or a Modal web endpoint (photos in, STL and
   holder out), and report numbers in the UI.
6. **Optional, for the $10K bonus:** move the planner to Muse Spark Open on Baseten or Modal.
7. **Write-up and submission:** README, demo video script (3 min, new work only), X post,
   make the repo public (ask), fill the submission form (Natalie submits).
