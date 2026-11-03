"""The scan CLI on synthetic full-resolution photo files, with SAM 3.1 replaced by the true outline."""
import os, json
import numpy as np, trimesh, cv2
from bevell3d import scan as scan_mod
from bevell3d.project import silhouette
from tests.synth import look_at, photo, camera_at
from tests.test_markers import K_TRUE, SIZE

FULL = 3            # photos written at 3x the working size, as a phone's are larger
CAMS = [camera_at(45, a, 380) for a in range(0, 360, 60)] + \
       [camera_at(10, a, 370) for a in range(0, 360, 45)] + [camera_at(85, 90, 330)]


def test_scan_from_files(tmp_path, monkeypatch):
    box = trimesh.creation.box((50.1, 46.2, 21.2))
    box.apply_translation((150, 100, 10.6))
    K_full = K_TRUE.copy(); K_full[:2] *= FULL
    full_size = (SIZE[0] * FULL, SIZE[1] * FULL)
    paths, truth = [], {}
    for k, c in enumerate(CAMS):
        R, t = look_at(c)
        v_full = {"rv": cv2.Rodrigues(R)[0], "tv": t.reshape(3, 1), "K": K_full}
        img = photo(K_full, R, t, full_size, seed=k)
        img[silhouette(box, v_full, full_size)] = 40          # the object, dark on the sheet
        p = str(tmp_path / f"IMG_{k:02d}.jpg")
        cv2.imwrite(p, img)
        paths.append(p)
        truth[f"IMG_{k:02d}"] = {"rv": v_full["rv"], "tv": v_full["tv"], "K": K_TRUE}
    monkeypatch.setattr(scan_mod, "object_mask",
                        lambda path, prompt: silhouette(box, truth[os.path.basename(path)[:-4]], SIZE))
    mesh, rep = scan_mod.scan(paths, "box", str(tmp_path / "out"))
    assert rep["posed"] == len(CAMS), rep
    assert abs(rep["focal_px"] - K_TRUE[0, 0]) / K_TRUE[0, 0] < 0.01, rep["focal_px"]
    ext = np.array(rep["extents_mm"])
    assert np.all(ext > np.array([50.1, 46.2, 21.2]) - 0.75) and np.all(ext < np.array([50.1, 46.2, 21.2]) + 3.5), ext
    assert json.load(open(tmp_path / "out" / "report.json"))["posed"] == len(CAMS)
