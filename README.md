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
   - an editable feature tree (revolve, extrude, loft, sweep, shell, fillet) as a
     CadQuery program and as a Fusion 360 script with named parameters and a timeline;
   - a holder to print: a pocket cut to the object's outline with 0.4 mm clearance, a
     filleted rim, a lead-in chamfer, finger notches and a chamfered foot, as STEP, STL,
     3MF (one tap opens it in Bambu Studio) and a DXF of its outline;
   - gripper pads for the SO-101 arm, shaped to the object, and where to grasp it.

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
  -> CAD: revolve, loft or a sewn solid; the holder and pads from the model
  -> optional: Muse Spark writes an editable feature tree, tuned against the photos
```

## Measured

Five scanned objects from Google Scanned Objects, rendered on the capture sheet in Blender
with 16 photos each, run through the whole pipeline with real model calls, and scored
against the true meshes:

- Camera positions within 0.17 to 0.33 mm (median).
- Size within 1.5 mm on 4 of 5 objects. The fifth, a white mouse, came out tight because
  white on a white sheet is hard to mask.
- Holders: on all five, a valid, watertight solid with a rounded rim, a lead-in and a
  chamfered foot. None touches the true object except the white mouse's (1.8 mm, from the
  masks above).
- The CAD agent's models came closest to the true surface on the bottle (1.21 mm mean) and
  the mug (2.09 mm, the only method that models its inside).

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
