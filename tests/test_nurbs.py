import os, numpy as np, pytest, trimesh
from bevell3d.nurbs import BLENDER, bezier_nets, nets_to_solid, fit_cage, scan_to_nurbs


def _cube_quads():
    V = np.array([[x, y, z] for x in (0, 30) for y in (0, 30) for z in (0, 30)], float)
    F = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]]
    return V, np.array(F)


def test_patches_from_a_cube_cage_sew_into_one_closed_smooth_solid():
    V, F = _cube_quads()
    solid = nets_to_solid(bezier_nets(V, F))
    assert solid.isValid() and len(solid.Faces()) == 6
    # The smooth surface sits inside its cage; fitted, it passes through the cage's corners.
    fitted = nets_to_solid(bezier_nets(fit_cage(V, F, 8), F))
    for c in V:
        d = min(np.linalg.norm(np.array(v.toTuple()) - c) for v in fitted.Vertices())
        assert d < 0.5, d


@pytest.mark.skipif(not os.path.exists(BLENDER), reason="needs Blender for QuadriFlow")
def test_a_scanned_blob_becomes_nurbs_within_a_tenth_of_a_millimetre(tmp_path):
    blob = trimesh.creation.icosphere(subdivisions=4, radius=25)
    blob.vertices[:, 2] *= 1.4; blob.vertices[:, 0] += 4 * np.sin(blob.vertices[:, 2] / 8)
    blob.apply_translation((150, 105, 35))
    path = str(tmp_path / "blob.stl"); blob.export(path)
    solid, rep = scan_to_nurbs(path, str(tmp_path / "blob.step"))
    assert rep["valid"] and abs(rep["volume_cm3"] / rep["scan_volume_cm3"] - 1) < 0.01, rep
    assert rep["off_scan_mean_mm"] < 0.1, rep
