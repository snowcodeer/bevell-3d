# Bevell 3D

Photos of an object on a printed sheet in. A true-size 3D model, editable CAD, a holder
to print and gripper pads for a robot arm out. Built for the Meta Global AI Developer
Hackathon (27 Oct to 4 Nov 2026).

## What is new in this hackathon

Everything in this repository was written during the hackathon (27 Oct to 4 Nov 2026). It
is built for [Bevell](https://bevell.app), an existing product that turns photos and scans
into 2D CAD, but it uses none of Bevell's code or services: Bevell's own code is not here and
is not part of this submission. Joining the two later means calling this service from Bevell,
or Bevell's public API from here, never sharing code.

## What it does

1. Print `assets/bevell_capture_sheet.pdf` on A4 and put the object in the middle.
2. Take 16 photos with a phone: 6 from 45°, 8 from low down, 2 from above.
3. Upload them. Back come:
   - the model at true size, as STEP and STL;
   - CAD that fits the object: a revolve for turned parts, sketches and extrusions for
     prismatic ones (with a Fusion 360 timeline: level heights and hole diameters are named
     parameters), and smooth NURBS surfaces for freeform ones;
   - on request, an editable feature tree Muse Spark writes (revolve, extrude, loft, sweep,
     shell, fillet), checked against the photos, as a CadQuery program and a Fusion 360 script;
   - a holder to print: a pocket cut to the object's outline with 0.4 mm clearance, a
     filleted rim, a lead-in chamfer, finger notches and a chamfered foot, as STEP, STL,
     3MF (one tap opens it in Bambu Studio) and a DXF of its outline;
   - for a robot arm (SO-101): gripper pads shaped to the object, and a fixture with finger
     reliefs and a printed tag, with the pick given in the tag's frame so the arm's camera
     can find the part and grip it.

## How Meta's models are used

| Model | Through | What it does here |
|---|---|---|
| Muse Spark | Meta Model API | Reads the photos and plans the scan: what the object is, the prompt for SAM 3.1, whether it is flat, turned or freeform, and which photos are blurred or cut off |
| SAM 3.1 | Meta Model API | Masks the object in every photo; the masks carve the shape |
| SAM 3D Objects | Modal (L40S) | Builds the full shape from one photo and mask, for freeform objects; it is scaled and placed by the measured silhouettes |
| Muse Spark | Meta Model API | The CAD agent: writes a feature tree, sees per-photo diff images of where its model misses, and revises |

## How it works

```
photos on the capture sheet
  -> Muse Spark plans the scan
  -> 22 ArUco markers: the camera's focal length, and each photo's pose (0.2 to 0.3 mm)
  -> SAM 3.1 masks every photo
  -> visual hull (voxel carve), or a revolved profile, or SAM 3D fitted to the silhouettes
  -> CAD: revolve, stacked extrusions, a loft that stays on the scan, or NURBS patches; the
     holder, pads and fixture
  -> optional: Muse Spark writes an editable feature tree, tuned against the photos
```

## Measured

**Fourteen objects with known true shapes**: nine scanned household objects from Google
Scanned Objects and four parts we designed (a bracket, an L-bracket, a gear and a sloped
stand), photographed on the capture sheet in Blender (16 photos each) and run through the
whole pipeline with real model calls, then scored against the true meshes
(`tools/bench_table.py`):

| Object | CAD | Size off | Model to truth | Holder catch | Agent tree to truth |
|---|---|---|---|---|---|
| Vitamin bottle | revolve | 1.4 mm | 1.5 mm | none | 1.4 mm |
| Tape roll | revolve | 1.1 | 1.0 | none | |
| Camera lens | revolve | 0.8 | 0.7 | none | 1.1 |
| Bracket | sketch + extrude | 2.7 | 0.9 | none | 0.7 |
| L-bracket | NURBS | 1.5 | 0.9 | 0.25 | 0.7 |
| Gear | NURBS | 1.3 | 1.3 | 0.29 | 0.9 |
| Sloped stand | NURBS | 0.7 | 1.4 | 0.35 | |
| Mario figure | NURBS | 1.8 | 0.9 | none | |
| Android figure | NURBS | 0.9 | 1.7 | none | |
| Alarm clock | NURBS | 1.9 | 2.6 | none | 3.4 |
| Mug | NURBS | 0.4 | 3.6 | none | 1.8 |
| Letter holder | NURBS | 2.4 | 4.8 | 0.41 | |
| Fish toothbrush holder | NURBS | 1.3 | 4.4 | 0.74 | |
| White mouse | NURBS | 6.4 | 1.5 | 1.6 | 2.2 |

- Camera positions within 0.2 to 0.3 mm (median). Size within 2 mm on 11 of 14 objects.
- "Model to truth" is the mean distance from the true surface. Open insides a camera cannot
  carve from outside (the mug, the letter holder's compartments, the fish's cup) cost 3 to 5
  mm; Muse Spark's feature tree models the mug's inside and comes to 1.8.
- The white mouse is the known weak case: white on a white sheet is hard to mask. Put a
  coloured card under white objects.
- Holders are valid, watertight solids with every edge treatment; most do not touch the true
  object at all.

**Feature trees in Fusion 360:** 15 of 16 trees, hand-written, Muse Spark's and the prismatic
route's, build the same body in Fusion and in CadQuery, within 0.6% in volume and 0.45 mm in
size, and both refuse the same impossible one (`tools/fusion_e2e.py`, through the BevellBridge
add-in). The sixteenth, Muse Spark's richer mouse, is a spline loft 0.65 mm apart on 128 mm
(volume +0.5%): Fusion's and OpenCascade's smooth lofts interpolate differently between
sections.

**Smooth NURBS:** Mario's 1,464 patches lie 0.06 mm from the scan and 0.93 mm from the true
figure (the scan itself is 0.92), and open in Fusion as one solid.

**What people do to photos** (`tools/user_tests.py`, the real pipeline): the minimum 8 photos,
photos from one side only, blurred, dark, shrunk to 640 px, 48 MP, rotated by their EXIF tag,
PNG and iPhone HEIC all come out within 2.5 mm of the true size. An unreadable photo is skipped
and named; photos of another object mixed in are left out. Sixteen copies of one photo, and
photos cropped so the sheet is gone, are refused with what to do instead. 13 of 13 pass. The web API is covered by 26 tests (passcode, daily cap, file types, ids,
path traversal).

**Robot fixture:** the printed tag is found by a camera at its id and size, and its pose 300 mm
away within 3 mm (`tests/test_fixture.py`, `tools/pick_preview.py`). The tag PDF's second
page is tag 41, for a second print of the fixture as the place station.

## Run it

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
export MODEL_API_KEY=...   # Meta Model API
.venv/bin/modal deploy modal_app/sam3d.py      # SAM 3D on Modal, for freeform objects
.venv/bin/uvicorn webapp.server:app --port 8300
```

Then open http://localhost:8300 on a phone or a laptop. A deployed copy runs at
https://nataliechan1963--bevell-3d-web.us-east.modal.run (`modal_app/web.py`); running a scan
there needs a passcode, and the examples are open to anyone. `python -m bevell3d.run --out out/x
photos/*.jpg` runs the same pipeline from the command line.

To build a feature tree inside Fusion 360, start the BevellBridge add-in
(`fusion_bridge/BevellBridge`) and run `python -m tools.fusion_e2e`.

## Credits

- Benchmark objects: [Google Scanned Objects](https://research.google/blog/scanned-objects-by-google-research-a-dataset-of-3d-scanned-common-household-items/),
  CC BY 4.0, via Gazebo Fuel's GoogleResearch collection.
- SAM 3D Objects and SAM 3.1 by Meta.
- MIT licence for the code. The Bevell name, logo and wordmark (`webapp/static/logo-icon.svg`,
  `webapp/static/bevell-wordmark.svg`) are Bevell's trademarks and are not covered by it.
