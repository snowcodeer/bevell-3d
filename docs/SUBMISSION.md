# Submission form: draft answers

Natalie fills the personal fields (scores, feedback, obstacle) and presses Submit herself.

**Team name:** Bevell

**Track:** Startups Track. **Problem statement:** Push the Frontier (manufacturing, robotics).

**Project description**

Bevell 3D turns sixteen phone photos into real CAD. Put an object on a printed sheet of markers,
take the photos the app guides you through, and get back a true-size 3D model as STEP and STL;
editable CAD that opens in Fusion 360 as a timeline with named dimensions (sketch and extrude
for prismatic parts, a revolve for turned ones, a feature tree Muse Spark writes for the rest);
smooth NURBS surfaces for organic shapes; a holder designed for 3D printing that opens in
Bambu Studio in one tap; and a fixture and gripper pads that let an SO-101 robot arm find and
pick the part. The markers give every photo its scale and camera position to a fraction of a
millimetre; Meta's models decide what the object is and where it is in each photo, and fill in
what the camera can't see. We tested it on scanned objects with known true shapes and on the
mistakes people make with photos.

**Public GitHub repository:** https://github.com/snowcodeer/bevell-3d

**Live demo:** https://nataliechan1963--bevell-3d-web.us-east.modal.run (a passcode for
running scans is in the form's notes; the examples are open)

**Describe your use of Meta products**

- **Muse Spark** (Meta Model API): reads the photos and plans each scan (what the object is,
  the prompt for SAM 3.1, whether it is turned, prismatic or freeform, which photos are
  blurred or cut off). As a CAD agent it writes the object as a feature tree (revolve, extrude,
  loft, sweep, shell, fillet), sees per-photo images of where its model misses, and revises;
  our optimiser tunes its dimensions against all the photos.
- **SAM 3.1** (Meta Model API): masks the object in every photo; the masks carve its shape.
- **SAM 3D Objects** (open weights, on Modal L40S GPUs): builds the full shape from one photo
  for freeform objects, including the sides no photo sees; we scale and place it by the
  measured silhouettes.

**Why are Meta's models important to your solution?**

Geometry from markers gives scale and camera positions, but not the object: something has to
find it in every photo, decide what kind of thing it is, and imagine the parts the camera never
saw. SAM 3.1's masks are the measurement itself (the visual hull is only as good as the masks),
SAM 3D supplies the hidden side of freeform objects, and Muse Spark turns a scan into the
design intent a person would draw: which features, in which order, with which dimensions.
Every dimension still comes from the photos; the models make the choices.

**X post:** (link once posted)

**Personal fields for Natalie:** partner feedback, the two Model API survey answers, the 0 to 5
scores for the Model API and Muse Code, the biggest obstacle, and the consent box.
