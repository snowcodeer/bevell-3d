"""Robot fingers for a hand tool lying flat: the two handles found, one saddle per jaw."""
import numpy as np, pytest, trimesh


def _mesh(make):
    s = make().val(); vs, fs = s.tessellate(0.05, 0.2)
    m = trimesh.Trimesh(np.array([v.toTuple() for v in vs]), np.array(fs))
    m.apply_translation((150 - m.centroid[0], 105 - m.centroid[1], -m.bounds[0][2]))
    return m


def test_scissors_get_a_saddle_on_each_finger_loops_outer_ring_that_clears_the_tool(tmp_path):
    from tools.make_parts import scissors
    from bevell3d.tool_fingers import write_tool_fingers
    m = _mesh(scissors)
    rep = write_tool_fingers(str(tmp_path), m)
    rings = sorted(s["width_mm"] for s in rep["saddles"])
    assert all(s["loop"] for s in rep["saddles"]), rep                 # both through a finger loop
    assert abs(rings[0] - 4.5) < 0.4 and abs(rings[1] - 5.0) < 0.4, rings
    assert all(abs(s["thickness_mm"] - 7.0) < 0.2 for s in rep["saddles"])
    assert 55 < rep["jaw_gap_tool_closed_mm"] < 70
    prints = trimesh.load(tmp_path / "tool_fingers.stl")
    assert prints.is_watertight and prints.extents[2] < 20               # flat on the bed, back down
    placed = trimesh.load(tmp_path / "tool_fingers_on_tool.stl")
    assert trimesh.boolean.intersection([placed, m], engine="manifold").volume < 2.0   # the grooves clear the tool


def test_pliers_handles_are_gripped_whole_at_their_own_angle():
    from tools.make_parts import pliers
    from bevell3d.tool_fingers import handles
    info = handles(_mesh(pliers))
    hs = info["handles"]
    assert not any(h["loop"] for h in hs)
    assert all(10 < h["width_mm"] < 14 for h in hs), hs
    assert hs[0]["angle_deg"] * hs[1]["angle_deg"] < 0 and all(5 < abs(h["angle_deg"]) < 11 for h in hs), hs   # splayed apart


def test_a_part_with_no_two_handles_is_not_a_tool():
    from tools.make_parts import bracket
    from bevell3d.tool_fingers import handles
    with pytest.raises(ValueError, match="No two handles"):
        handles(_mesh(bracket))


def test_the_so101_works_the_scissors_in_simulation(tmp_path):
    """MuJoCo, the SO-101's own jaws: a small gripper opening opens the blades enough for paper,
    the loop's ball joint holds, and the rail the loop slides along fits on the finger."""
    import os
    from tools.make_parts import scissors
    from bevell3d.scissors_sim import tune
    if not os.path.exists("third_party/so101/assets/moving_jaw_so101_v1.stl"):
        pytest.skip("SO-101 files not present")
    _mesh(scissors).export(tmp_path / "model.stl")
    xml, rep = tune(str(tmp_path))
    assert rep["held"] and rep["blades_open_deg"] >= 15, {k: rep[k] for k in ("blades_open_deg", "joint_gap_max_mm")}
    assert 3 < rep["gripper_open_deg"] < 21
    assert 5 < rep["rail_mm"] < 60, rep["rail_mm"]
