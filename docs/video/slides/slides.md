# Video slides and voice-over (about 3:00)

Slides are `slide-NN.png` (1920x1080) and `slide-NN@2x.png` (3840x2160). The live app footage
goes between slides 2 and 3 and after slide 10. Rebuild with
`.venv/bin/python docs/video/slides/make_images.py` then `.venv/bin/python docs/video/slides/build.py`.

| # | Slide | Seconds | Voice-over |
|---|---|---|---|
| 1 | Robotics is moving fast. Prototyping should move faster. | 6 | "Robotics is moving fast. Prototyping should move even faster." |
| 2 | A robot arm can't use a human tool. | 7 | "A robot arm can't use a human tool. Making it custom grippers is usually an afternoon of CAD, a print, and another try." |
| app | Phone: Make custom robot grippers, the guided camera, the progress screen | 35 | "So I take a few photos of the scissors on a printed sheet. The app guides every angle." |
| 3 | Photos in. CAD out. (the photos) | 6 | "That's all it needs: phone photos on a sheet." |
| 4 | Every photo, measured. (squares, cameras) | 10 | "The sheet's squares give every photo its scale and its camera position, to a fraction of a millimetre." |
| 5 | SAM 3.1 finds the object in every photo | 10 | "Muse Spark looks at the photos and plans the scan. SAM 3.1 then cuts the scissors out of every photo, and those masks are the measurement." |
| 6 | SAM 3D builds the whole shape | 10 | "SAM 3D Objects builds the whole shape, including the sides no photo sees, and the photos size and place it." |
| 7 | The photos' edge, SAM 3D's finger holes | 10 | "Each model is used where it's right. On clear plastic the masks fill the finger holes; SAM 3D sees them. So the outline comes from the photos, the holes from SAM 3D." |
| 8 | The pivot is the screw | 8 | "The pivot is found in the photo from above: it's the screw. It goes on the gripper's own hinge, so the blades open exactly as far as the jaw." |
| 9 | Grippers designed, not guessed | 12 | "Then it designs two new parts for the SO-101. Each finger loop snaps into a clip made for it, with the scissors cut out at 0.4 millimetres clearance. They bolt on with the stock screws." |
| 10 | Tested in MuJoCo first | 10 | "And it's tested in MuJoCo first: 25.8 degrees of jaw, 25.8 degrees of blade, and nothing collides." |
| app | Result screen: Original, Model, Grippers tab, print screen into Bambu Studio | 20 | "Everything comes back in the browser: the model, the grippers, and two parts ready to print." |
| 11 | How Bevell 3D works (architecture) | 15 | "Under the hood: guided photos, the sheet's markers, Muse Spark, SAM 3.1 and SAM 3D, then CAD. The gripper design itself is deterministic: no guessing." |
| 12 | Built in three days. | 8 | "Built in three days on Muse Spark, SAM 3.1 and SAM 3D. It's a beta, for the SO-101 and scissors for now. Try it at the link." |

Total: about 2:47 with the app footage at 55 s; stretch the footage or slide 11 to fill 3:00.

Rules: never show the passcode or a key. The robot's motion is taught and replayed, not planned.
The clips have not been printed and tested yet: say "first prototype" and "tested in simulation".
