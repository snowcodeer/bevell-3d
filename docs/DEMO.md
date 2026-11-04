# Demo video: script and shots (3 minutes)

The story in one line: **photos in, CAD out: measured, editable, printable, and ready for a
robot.** Every claim on screen is one we measured; the numbers are in the README.

## Before recording

- **Sheet:** print `assets/bevell_capture_sheet.pdf` on A4 at 100% ("actual size", not "fit").
  A marker square should measure 22 mm with a ruler.
- **Objects, one of each kind:**
  - round: a bottle, a can or a mug (revolved CAD, round holder);
  - prismatic: a hobby servo, or a spare STS3215 from the SO-101 itself (sketch-and-extrude
    CAD that opens in Fusion as a timeline, and the part the robot moves: "the robot picks up
    its own spare part");
  - freeform: a toy or figure (smooth NURBS surfaces).
  - Not white on the white sheet: put a coloured card under a white object. Keep it inside the
    white area, clear of the squares.
- **Live app:** open https://nataliechan1963--bevell-3d-web.us-east.modal.run two or three
  minutes before (the first request wakes the container). Have the passcode ready.
- **Fusion 360** open; **Bambu Studio** installed; the **SO-101** calibrated, with the gripper
  pads on the jaws.
- **Two stations:** print the servo's `fixture.3mf` twice. Print `tag.pdf` at 100%; stick page
  1 (tag 40) in one fixture and page 2 (tag 41) in the other, each with its arrow towards the
  part. Tape both fixtures to the table where the arm reaches them.
- **The arm's motion:** the fixtures hold the servo at the same pose every time, which is what
  lets a taught motion work every time. Teach the pick from fixture 40 and the place into
  fixture 41 once (LeRobot teleoperation with the leader arm, or recorded joint targets) and
  replay it on camera. Run `python -m tools.pick_preview frame.jpg fixture.json` (and
  `--tag-id 41`) on a frame from the arm's camera for the overlay: tag found, jaws through the
  finger reliefs. Nothing here drives the arm from the camera; say "the fixture puts the part
  where the robot expects it", not "the robot sees the part".
- **Capture:** screen-record the phone (QuickTime, iPhone over USB) and film the hands with a
  second camera. 1080p is enough.
- **Fallback:** if a live scan runs slow on camera, cut to one of the examples on the start
  screen; they are full runs of the same pipeline. "Hobby servo" is the demo part, already
  scanned, with Muse Spark's tree and the fixture.
- **Timing:** a scan takes about 3 to 5 minutes. "Make it editable" takes 10 to 20 (Muse
  Spark writes the tree, then 160 builds a round tune it against the photos): start it before
  filming the Fusion shot, or cut the wait in the edit.

## Shots

| Time | On screen | Voice-over |
|---|---|---|
| 0:00 to 0:12 | Hands put a part on the printed sheet. Title: "Photos in. CAD out." | "Turning a real object into CAD still means calipers, guesswork and an afternoon. This takes sixteen phone photos." |
| 0:12 to 0:40 | The phone: the guide fills ring by ring (six from 45 degrees, eight low, two from above); review; "Make my CAD". | "The squares on the sheet give every photo its scale and its camera position, to a fraction of a millimetre. The app tells you where to stand." |
| 0:40 to 1:05 | The "Making" screen as each stage lights up. Lower thirds: Muse Spark, SAM 3.1, SAM 3D. | "Muse Spark looks at the photos and plans the scan. SAM 3.1 cuts the object out of every photo. For freeform shapes, SAM 3D fills in the side the camera can't see, and we fit it to the photos at true size." |
| 1:05 to 1:30 | The result: the 3D model turning; the size. Cut to calipers on the real object, then back to the same number in the app. | "Measured, not guessed: within a millimetre or two of the calipers." |
| 1:30 to 2:00 | Editable CAD. Prismatic part: "Already editable", open the Fusion script, the timeline and named parameters appear; change a height and the part updates. Or "Make it editable": Muse Spark writes a feature tree, the photo check (red and cyan) flashes, the tree opens in Fusion. | "Not a mesh: real CAD. Sketches and extrusions with named dimensions, or a feature tree Muse Spark writes and our photos check, and it opens in Fusion." |
| 2:00 to 2:15 | A freeform object (the figure) in Fusion as smooth NURBS; fillet an edge or shell it. | "Organic shapes come out as smooth surfaces, not triangles, so you can keep designing on them." |
| 2:15 to 2:40 | "Open in Bambu Studio" from the print screen; a time-lapse of the holder printing; the part drops into its holder. Then the two fixtures: the overlay shows tag 40 found and the jaws planned through the finger reliefs; the SO-101 picks the servo with its fitted pads and sets it down in the fixture with tag 41. | "One tap sends a holder to the printer: rounded rim, lead-in, no supports. And the same scan makes fixtures a robot can use: finger reliefs where its jaws go, a tag that tells its camera where the part sits, and the grasp written out. Print it twice and you have a pick-and-place station from one scan." |
| 2:40 to 3:00 | Numbers card, then the Meta models card, then the URL. | "Tested on scanned objects with known true shapes and on the mistakes people make with photos. Built on Meta's Muse Spark, SAM 3.1 and SAM 3D. Try it: link below." |

## Ready-made shots

- `docs/images/robot_pick.png`: the scanned bracket in its fixture, rendered from a robot's
  camera, with the tag found and the planned pick drawn (jaws through the finger reliefs,
  approach from above). Made by `tools/render_fixture_scene.py` and `tools/pick_preview.py`;
  the pick lands 0.3 mm sideways and 3 mm in depth from the truth at 33 cm. Use it as B-roll
  for the robot section, or film the same overlay live from the arm's camera with
  `python -m tools.pick_preview photo.jpg fixture.json`.
- `docs/images/servo_pick.png`: the same for the servo, the demo's part (the pick lands 3 mm
  from the truth at 31 cm). Its example on the start screen has Muse Spark's tree: case
  39.2 × 18.8 × 36.9 mm (true 40.7 × 19.7 × 37), ears 52.9 long at 27.0 up (54.5 at 26.5),
  boss ⌀12.5 at 10.2 off-centre (⌀13 at 10.35), four holes, 12 named parameters, 0.59 mm from
  the true surface. Open its Fusion script and change `flange_z` or `hole_d` on camera.
- The examples on the start screen cover each kind: Vitamin bottle and Tape roll (revolve),
  Bracket (sketch + extrude from the scan), Hobby servo, Gear, Mug and Alarm clock (smooth
  NURBS, each with Muse Spark's tree: the mug's handle, the gear's teeth), Mario and Fish
  (smooth NURBS). Every example has its holder, pads and robot fixture.

## Numbers card (from the README, checked before recording)

- Camera positions: 0.2 to 0.3 mm.
- Sizes: within 2 mm on 12 of 15 objects; editable CAD within 1 to 2 mm of the true surface.
- Feature trees build the same body in Fusion 360 and CadQuery: 16 of 17 test trees, within 0.6%
  in volume (the sixteenth, a spline loft, is 0.65 mm apart on 128 mm).
- Smooth NURBS: 0.06 mm from the scan.
- Photo mistakes: 13 of 13 user tests pass. Blurred, dark, tiny, huge, rotated, HEIC, PNG and
  one-sided sets come out within 2.5 mm; photos from one spot are refused with a reason.

## Lines to avoid

- Don't promise accuracy under a millimetre for the object itself; the cameras are that good,
  the shapes are within one to two.
- Don't show a white object on the white sheet without a backing.
- Don't say it is part of bevell.app yet; it is built for it and talks to nothing of Bevell's.
- Don't say the robot finds the part by vision and plans its own path: the tag gives the pose
  and the overlay, the taught motion moves the arm.
