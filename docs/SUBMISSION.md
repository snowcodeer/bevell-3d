# Submission form: draft answers

Natalie fills the personal fields (scores, feedback, obstacle) and presses Submit herself.
Due 4 Nov 2026, 9pm ET (02:00 UK, Thu 5 Nov).

**Team name:** Bevell

**Track:** Startups Track. **Problem statement:** Push the Frontier (manufacturing, robotics).

**Project name:** Bevell 3D

**One-liner:** Photos of a tool in, custom robot grippers to print out, tested in simulation.

**Project description**

Bevell 3D turns about fifteen phone photos into measured CAD. Put an object on a printed sheet
of markers, follow the guided camera, and get back a true-size model as STEP and STL: sketch and
extrude for prismatic parts, a revolve for turned ones, smooth NURBS surfaces for freeform ones,
an editable feature tree Muse Spark writes on request, and a holder that opens in Bambu Studio
in one tap.

The headline is custom robot grippers for a tool (beta, SO-101 only). Photograph a pair of
scissors and Bevell 3D designs new jaw parts for the SO-101 arm that replace its stock ones: the
scissors' pivot is found on the screw in the photo from above and placed on the gripper's own
hinge, so the blades open and close one to one with the jaw, and each finger loop snaps into a
clip shaped to it. The design is checked in MuJoCo before anything is printed. On the live run
of a real pair: the gripper opens 25.8°, the blades open 25.8°, and the parts and blades never
collide. Unscrew the stock jaw, screw the new parts on, snap the scissors in, and the arm cuts.

The sheet's markers give every photo its scale and camera position to a fraction of a
millimetre. Meta's models decide what the object is, find it in every photo and fill in what
the camera can't see. Every dimension comes from the photos; the models make choices, never
measurements. Tested on fifteen objects with known true shapes and on thirteen kinds of photo
mistakes.

**Public GitHub repository:** https://github.com/snowcodeer/bevell-3d

**What was built during the hackathon:** all of it. The repository was written from 2 to 4 Nov
2026 (first commit 3 Nov, 00:36 UTC), inside the hackathon window. It is built for Bevell
(bevell.app), an existing 2D photo-to-CAD product, but contains none of Bevell's code and calls
none of its services for the pipeline. The README says so at the top.

**Live demo:** https://nataliechan1963--bevell-3d-web.us-east.modal.run

- The examples on the start screen are open to everyone.
- Judges: the passcode is in the form's notes.
- Everyone else can run a scan with their own Meta Model API key, or with a Bevell API key
  from a Bevell Unlimited subscription.
- A finished gripper run on a real pair of scissors:
  https://nataliechan1963--bevell-3d-web.us-east.modal.run/#result/f684f76b871f

**Describe your use of Meta products**

- **Muse Spark** (Meta Model API): reads the photos and plans each scan: what the object is,
  the prompt for SAM 3.1, whether it is turned, prismatic or freeform, and which photos are
  blurred or cut off. As a CAD agent it writes the object as a feature tree (revolve, extrude,
  loft, sweep, shell, fillet), looks at per-photo images of where its model misses, and
  revises. Our optimiser then tunes its dimensions against all the photos.
- **SAM 3.1** (Meta Model API): masks the object in every photo. The masks carve its shape and
  give the tool its outline from above, finger loops included.
- **SAM 3D Objects** (open weights, on Modal L40S GPUs): builds the full shape from one photo,
  including the sides no photo sees. We scale and place it by the measured silhouettes. The
  scissors in the gripper demo are SAM 3D's model, fitted at 153 x 58 x 10 mm.

**Why are Meta's models important to your solution?**

The markers give scale and camera positions, but not the object. Something has to find it in
every photo, decide what kind of thing it is, and imagine the parts the camera never saw. SAM
3.1's masks are the measurement itself (the shape is only as good as the masks), SAM 3D
supplies the hidden side of freeform objects and of thin, partly clear tools like scissors, and
Muse Spark turns a scan into the design intent a person would draw: which features, in which
order, with which dimensions. The grippers then take the measured outline and SAM 3D's shape
and design around them deterministically, so the same scissors always give the same parts.

**Demo video:** (YouTube or Loom link, 3 minutes, public or unlisted)

**X post:** (link once posted; drafts in `docs/X_POST.md`)

**Personal fields for Natalie:** partner feedback, the two Model API survey answers, the 0 to 5
scores for the Model API and Muse Code, the biggest obstacle, and the consent box.

## Before pressing Submit

- Open the live link and check that the own-key and Bevell Unlimited options are deployed. If
  either is not, delete it from the "Live demo" list above.
- Put the passcode in the form's notes field only, never in the repo or the video.
- Check the repo is still public and `git log origin/main` holds no personal details.
- The video shows only work from the hackathon (the rules disqualify older work shown as new).
