# Demo video: script and shots (3 minutes)

The story in one line: **photos in, CAD out: measured, editable, printable, and ready for a
robot.** Every claim on screen is one we measured; the numbers are in the README.

## Before recording

- **Sheet:** print `assets/bevell_capture_sheet.pdf` on A4 at 100% ("actual size", not "fit").
  A marker square should measure 22 mm with a ruler.
- **Objects, one of each kind:**
  - round: a bottle, a can or a mug (revolved CAD, round holder);
  - prismatic: a part with flat faces and holes, such as a bracket or a printed part
    (sketch-and-extrude CAD that opens in Fusion as a timeline);
  - freeform: a toy or figure (smooth NURBS surfaces).
  - Not white on the white sheet: put a coloured card under a white object. Keep it inside the
    white area, clear of the squares.
- **Live app:** open https://nataliechan1963--bevell-3d-web.us-east.modal.run two or three
  minutes before (the first request wakes the container). Have the passcode ready.
- **Fusion 360** open; **Bambu Studio** installed; the **SO-101** calibrated, with the printed
  fixture, its tag stuck in the recess, and the gripper pads on the jaws.
- **Capture:** screen-record the phone (QuickTime, iPhone over USB) and film the hands with a
  second camera. 1080p is enough.
- **Fallback:** if a live scan runs slow on camera, cut to one of the examples on the start
  screen; they are full runs of the same pipeline.

## Shots

| Time | On screen | Voice-over |
|---|---|---|
| 0:00 to 0:12 | Hands put a part on the printed sheet. Title: "Photos in. CAD out." | "Turning a real object into CAD still means calipers, guesswork and an afternoon. This takes sixteen phone photos." |
| 0:12 to 0:40 | The phone: the guide fills ring by ring (six from 45 degrees, eight low, two from above); review; "Make my CAD". | "The squares on the sheet give every photo its scale and its camera position, to a fraction of a millimetre. The app tells you where to stand." |
| 0:40 to 1:05 | The "Making" screen as each stage lights up. Lower thirds: Muse Spark, SAM 3.1, SAM 3D. | "Muse Spark looks at the photos and plans the scan. SAM 3.1 cuts the object out of every photo. For freeform shapes, SAM 3D fills in the side the camera can't see, and we fit it to the photos at true size." |
| 1:05 to 1:30 | The result: the 3D model turning; the size. Cut to calipers on the real object, then back to the same number in the app. | "Measured, not guessed: within a millimetre or two of the calipers." |
| 1:30 to 2:00 | Editable CAD. Prismatic part: "Already editable", open the Fusion script, the timeline and named parameters appear; change a height and the part updates. Or "Make it editable": Muse Spark writes a feature tree, the photo check (red and cyan) flashes, the tree opens in Fusion. | "Not a mesh: real CAD. Sketches and extrusions with named dimensions, or a feature tree Muse Spark writes and our photos check, and it opens in Fusion." |
| 2:00 to 2:15 | A freeform object (the figure) in Fusion as smooth NURBS; fillet an edge or shell it. | "Organic shapes come out as smooth surfaces, not triangles, so you can keep designing on them." |
| 2:15 to 2:40 | "Open in Bambu Studio" from the print screen; a time-lapse of the holder printing; the part drops into its holder. Then the robot fixture: the arm's camera finds the tag, and the SO-101 picks the part with its fitted pads. | "One tap sends a holder to the printer: rounded rim, lead-in, no supports. And the same scan makes a fixture a robot can use: a tag that tells its camera where the part is, finger reliefs where its jaws go, and the pick, ready to run." |
| 2:40 to 3:00 | Numbers card, then the Meta models card, then the URL. | "Tested on scanned objects with known true shapes and on the mistakes people make with photos. Built on Meta's Muse Spark, SAM 3.1 and SAM 3D. Try it: link below." |

## Numbers card (from the README, checked before recording)

- Camera positions: 0.2 to 0.3 mm.
- Sizes: within 1.5 mm on most objects; editable CAD within 1 to 2 mm of the true surface.
- Feature trees build identically in Fusion 360 and CadQuery (10 of 10 test trees).
- Smooth NURBS: 0.06 mm from the scan.
- Photo mistakes: blurred, dark, tiny, huge, rotated, HEIC, PNG and one-sided sets all come
  out at the right size; photos from one spot are refused with a reason.

## Lines to avoid

- Don't promise accuracy under a millimetre for the object itself; the cameras are that good,
  the shapes are within one to two.
- Don't show a white object on the white sheet without a backing.
- Don't say it is part of bevell.app yet; it is built for it and talks to nothing of Bevell's.
