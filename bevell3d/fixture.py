"""A holder a robot can work from: gripper reliefs where the jaws go, and a tag that tells the
robot's camera where the fixture is, so it knows where the part is and how to pick it.

- The finger notches move onto the grasp's squeeze axis and are sized from the gripper pads:
  wide enough for a jaw and deep enough that the pads reach the part at the grasp height.
- A low tab at one end of the holder carries a 30 mm recess for a printed ArUco tag (4x4,
  id 40 by default, outside the capture sheet's 0 to 21). `tag.pdf` prints it at size.
- `fixture.json` gives the pick in the marker's own frame (OpenCV's): origin at its centre, x to
  its right, y to its top edge, which goes towards the part, z up. A robot that
  detects the tag (cv2.aruco, camera intrinsics) composes its pose with these numbers.

    python -m bevell3d.fixture <scan result dir>     # writes fixture.step/.stl/.3mf, fixture.json, tag.pdf
"""
import json, math, os
import numpy as np, trimesh, cadquery as cq
from .cad import HolderParams, holder_cad, footprint, to_mesh
from .gripper import PadParams, grasp_frame

TAG_DICT, TAG_ID, TAG_MM, TAB_MM = "DICT_4X4_50", 40, 30.0, 38.0
PLACE_TAG_ID = 41      # a second print of the same fixture, for pick and place


def fixture_cad(mesh, pad=PadParams(), hp=HolderParams(), tag_id=TAG_ID):
    """(solid, report). The holder of `mesh` with gripper reliefs and a tag tab."""
    height = float(mesh.bounds[1][2] - mesh.bounds[0][2])
    depth = min(hp.depth_fraction * height, hp.max_depth)
    centre, dvec, uvec = grasp_frame(mesh, pad)
    zg = float(centre[2] - mesh.bounds[0][2])            # grasp height above the part's base
    # Reliefs: the pads reach pad.height / 2 below the grasp; give the jaw 2 mm under that and
    # 3 mm beside it. A U notch of radius r centred on the rim is 2r wide and r deep.
    need_depth = depth - (zg - pad.height / 2 - 2.0)
    r = max(pad.width / 2 + 3.0, min(need_depth, depth + 0.5))
    hp = HolderParams(**{**hp.__dict__, "notch_radius": r, "notch_depth": 1.0})
    holder, info, pocket, outer = holder_cad(mesh, hp)
    total = hp.floor + depth
    # Tag tab beyond the outer wall along the long axis, as low as the floor plus 1 mm.
    ring = np.asarray(outer.exterior.coords)
    c2 = np.asarray(centre[:2]); u2 = np.asarray(uvec[:2]) / np.linalg.norm(uvec[:2])
    reach = float(np.max((ring - c2) @ u2))
    tab_c = c2 + u2 * (reach + TAB_MM / 2 - 2.0)          # overlaps the wall by 2 mm to join it
    yaw = math.degrees(math.atan2(u2[1], u2[0]))
    tab_h = hp.floor + 1.0
    tab = (cq.Workplane("XY").rect(TAB_MM, TAB_MM).extrude(tab_h)
           .edges("|Z").fillet(3.0)
           .rotate((0, 0, 0), (0, 0, 1), yaw).translate((tab_c[0], tab_c[1], 0)))
    recess = (cq.Workplane("XY").rect(TAG_MM + 0.4, TAG_MM + 0.4).extrude(1.0)
              .rotate((0, 0, 0), (0, 0, 1), yaw).translate((tab_c[0], tab_c[1], tab_h - 0.6)))
    solid = cq.Workplane("XY").add(holder).union(tab).cut(recess).val()
    # The pick, in the tag's frame: origin at the tag centre on the recess floor, x from the tag
    # towards the part, z up. The part sits on the pocket floor, so its base is at hp.floor.
    tag_origin = np.r_[tab_c, tab_h - 0.6]
    # The marker's own frame (OpenCV's): x to its right, y to its top edge, z out of it. The
    # sticker goes in with its top edge towards the part, as tag.pdf says, so y points there.
    y_axis = np.r_[-u2, 0.0]; z_axis = np.array([0.0, 0.0, 1.0]); x_axis = np.cross(y_axis, z_axis)
    R = np.vstack([x_axis, y_axis, z_axis])                # rows: tag axes in the holder frame
    base_shift = hp.floor - float(mesh.bounds[0][2])       # the part is seated on the floor
    grasp_pt = np.r_[centre[:2], centre[2] + base_shift]
    to_tag = lambda p: (R @ (np.asarray(p) - tag_origin)).round(2).tolist()
    squeeze = (R @ np.r_[dvec[:2], 0.0]).round(4).tolist()
    width = float(np.ptp((mesh.vertices[:, :2] - centre[:2]) @ dvec[:2]))
    report = {
        "tag": {"dictionary": TAG_DICT, "id": tag_id, "size_mm": TAG_MM,
                "frame": "the marker's own (OpenCV): origin at its centre, x to its right, y to its top edge (towards the part), z up; mm",
                "stick": "top edge of the printed tag towards the part",
                "place_id": PLACE_TAG_ID,
                "place": "print the fixture twice and stick this tag in the second for a place fixture: the grasp is the same in its frame"},
        "grasp": {"centre_mm": to_tag(grasp_pt), "squeeze_axis": squeeze, "approach": [0.0, 0.0, -1.0],
                  "jaw_open_mm": round(width + 2 * (pad.thickness + 8.0), 1),
                  "jaw_closed_on_part_mm": round(width + 2 * (pad.clearance + pad.thickness), 1),
                  "pregrasp_mm": to_tag(grasp_pt + np.array([0, 0, height + 40.0]))},
        "part": {"size_mm": [round(float(e), 1) for e in mesh.extents], "seated_base_z_mm": round(float(hp.floor - tag_origin[2]), 2),
                 "seat_shift_mm": [0.0, 0.0, round(float(base_shift), 3)]},
        # Where the tag sits in the holder's own frame (the scan's sheet frame), for simulation.
        "tag_in_holder": {"origin_mm": tag_origin.round(3).tolist(), "x_axis": x_axis.round(6).tolist(),
                          "y_axis": y_axis.round(6).tolist(), "z_axis": z_axis.round(6).tolist()},
        "fixture": {**{k: info[k] for k in ("holder_mm", "pocket_depth_mm", "valid")}, "relief_mm": round(2 * r, 1),
                    "relief_depth_mm": round(r, 1), "tab_mm": TAB_MM, "dfm": info["dfm"]},
    }
    return solid, report


def tag_pdf(path, tag_id=TAG_ID, size_mm=TAG_MM, dpi=600, place_id=PLACE_TAG_ID):
    """The tag on an A4 page at exact size, with its id printed under it; then, unless
    `place_id` is None, the place fixture's tag on a second page."""
    pick = tag_page(tag_id, size_mm, dpi, "Pick fixture")
    more = [tag_page(place_id, size_mm, dpi, "Place fixture: a second print of the same fixture")] if place_id is not None else []
    pick.save(path, "PDF", resolution=dpi, save_all=True, append_images=more)


def tag_page(tag_id=TAG_ID, size_mm=TAG_MM, dpi=600, role=None):
    import cv2
    from PIL import Image, ImageDraw
    px = int(round(size_mm / 25.4 * dpi))
    marker = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, TAG_DICT)), tag_id, px)
    page = Image.new("L", (int(210 / 25.4 * dpi), int(297 / 25.4 * dpi)), 255)
    x0, y0 = (page.width - px) // 2, int(40 / 25.4 * dpi)
    page.paste(Image.fromarray(marker), (x0, y0))
    d = ImageDraw.Draw(page)
    d.rectangle([x0 - 2, y0 - 2, x0 + px + 2, y0 + px + 2], outline=180)
    cx, top = x0 + px // 2, y0 - int(3 / 25.4 * dpi)            # an arrow over the top edge
    d.polygon([(cx, top - int(6 / 25.4 * dpi)), (cx - int(4 / 25.4 * dpi), top), (cx + int(4 / 25.4 * dpi), top)], fill=0)
    d.text((cx + int(6 / 25.4 * dpi), top - int(5 / 25.4 * dpi)), "this edge towards the part", fill=0)
    d.text((x0, y0 + px + int(4 / 25.4 * dpi)), f"Bevell fixture tag {TAG_DICT} id {tag_id}, {size_mm:.0f} mm. Print at 100%, cut on the grey line.", fill=0)
    if role:
        d.text((x0, y0 + px + int(8 / 25.4 * dpi)), role, fill=0)
    return page


def write_fixture(out_dir, mesh, tag_id=TAG_ID):
    solid, report = fixture_cad(mesh, tag_id=tag_id)
    cq.exporters.export(cq.Workplane().add(solid), os.path.join(out_dir, "fixture.step"))
    m = to_mesh(solid); m.export(os.path.join(out_dir, "fixture.stl")); m.export(os.path.join(out_dir, "fixture.3mf"))
    tag_pdf(os.path.join(out_dir, "tag.pdf"), tag_id)
    json.dump(report, open(os.path.join(out_dir, "fixture.json"), "w"), indent=1)
    return report


if __name__ == "__main__":
    import sys
    d = sys.argv[1]
    print(json.dumps(write_fixture(d, trimesh.load(os.path.join(d, "model.stl"))), indent=1))
