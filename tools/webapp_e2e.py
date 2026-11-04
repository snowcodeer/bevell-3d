"""End to end through the web app's API: upload photos, wait for the scan, download and open
every file it offers.

    .venv/bin/python -m tools.webapp_e2e out/bench/bottle/photos [--base http://127.0.0.1:8300] [--agent] [--passcode X]
"""
import argparse, glob, io, json, os, sys, tempfile, time
import requests


def check_file(name, data):
    """Open a download the way a user's software would; return a short description or raise."""
    suffix = os.path.splitext(name)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data); path = f.name
    try:
        if suffix == ".step":
            import cadquery as cq
            s = cq.importers.importStep(path).val()
            assert s.isValid() and s.Volume() > 0
            return f"STEP solid, {s.Volume() / 1000:.1f} cm3"
        if suffix in (".stl", ".3mf"):
            import trimesh
            m = trimesh.load(path, force="mesh")
            assert len(m.faces) > 0
            return f"{len(m.faces)} faces, {'watertight' if m.is_watertight else 'open'}, {' x '.join(f'{e:.1f}' for e in m.extents)} mm"
        if suffix == ".dxf":
            import ezdxf
            doc = ezdxf.readfile(path)
            n = len(doc.modelspace())
            assert n > 0
            return f"DXF, {n} entities on {sorted({e.dxf.layer for e in doc.modelspace()})}"
        if suffix == ".json":
            json.loads(data)
            return "JSON"
        if suffix == ".zip":
            import zipfile
            names = zipfile.ZipFile(path).namelist()
            assert any(n.endswith(".py") for n in names) and any(n.endswith(".manifest") for n in names)
            return f"zip: {', '.join(sorted(names))}"
        if suffix == ".py":
            compile(data.decode(), name, "exec")
            return "Python, compiles"
        return f"{len(data)} bytes"
    finally:
        os.remove(path)


def main(photo_dir, base, agent=False, passcode=""):
    auth = {"x-passcode": passcode} if passcode else {}
    photos = sorted(glob.glob(os.path.join(photo_dir, "*.jpg")))
    t0 = time.time()
    r = requests.post(base + "/api/scans", files=[("photos", (os.path.basename(p), open(p, "rb"), "image/jpeg")) for p in photos], headers=auth, timeout=300)
    assert r.ok, r.text
    sid = r.json()["id"]
    print(f"uploaded {len(photos)} photos -> scan {sid}")
    seen = set()
    while True:
        st = requests.get(f"{base}/api/scans/{sid}", timeout=30).json()
        if st.get("stage") not in seen:
            seen.add(st.get("stage")); print(f"  {time.time() - t0:6.1f} s  {st.get('state')}: {st.get('stage')} {st.get('detail', '')}")
        if st["state"] in ("done", "failed"):
            break
        time.sleep(1.5)
    assert st["state"] == "done", st.get("error")
    s = st["summary"]
    print(f"done in {time.time() - t0:.0f} s: {s['plan']['object']!r}, {s['plan']['route']}, model {s['model_mm']} mm from {s['model_source']}, CAD {s.get('cad', {}).get('kind')}")
    if agent:
        requests.post(f"{base}/api/scans/{sid}/agent", headers=auth, timeout=30).raise_for_status()
        while True:
            st = requests.get(f"{base}/api/scans/{sid}", timeout=30).json()
            a = st.get("agent") or {}
            if a.get("state") in ("done", "failed"):
                break
            time.sleep(5)
        assert a["state"] == "done", a.get("error")
        print(f"agent: IoU {a['report']['best_iou']:.3f} in {a['report']['seconds']:.0f} s")
    bad = 0
    for f in st["files"]:
        data = requests.get(f["url"], timeout=60).content
        try:
            print(f"  ok   {f['name']:<22} {check_file(f['name'], data)}")
        except Exception as e:
            bad += 1; print(f"  FAIL {f['name']:<22} {type(e).__name__}: {e}")
    sheet = requests.get(base + "/sheet.pdf", timeout=30)
    print(f"  {'ok  ' if sheet.ok and sheet.content[:4] == b'%PDF' else 'FAIL'} sheet.pdf ({len(sheet.content) // 1024} KB)")
    print(f"{len(st['files']) - bad} of {len(st['files'])} files open")
    return sid, bad


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("photos"); ap.add_argument("--base", default="http://127.0.0.1:8300"); ap.add_argument("--agent", action="store_true")
    ap.add_argument("--passcode", default=os.environ.get("BEVELL3D_PASSCODE", ""))
    a = ap.parse_args()
    sid, bad = main(a.photos, a.base, a.agent, a.passcode)
    sys.exit(1 if bad else 0)
