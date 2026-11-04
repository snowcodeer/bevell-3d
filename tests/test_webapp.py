"""The web app's API as a user (or a curious judge) would poke at it, without starting a scan."""
import io, json, os, time
import pytest
from fastapi.testclient import TestClient
import webapp.server as server

JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")   # a tiny JPEG-shaped file


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "SCANS", str(tmp_path))
    monkeypatch.setattr(server, "PASSCODE", "")
    monkeypatch.setattr(server, "DAILY_CAP", 0)
    started = []
    monkeypatch.setattr(server, "_work", lambda scan_id, paths: started.append((scan_id, paths)))
    monkeypatch.setattr(server.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda self: target(*args)})())
    c = TestClient(server.app)
    c.started = started
    return c


def photos(n, name="IMG_{:02d}.jpg"):
    return [("photos", (name.format(i), io.BytesIO(JPEG), "image/jpeg")) for i in range(n)]


def test_open_by_default_and_says_so(client):
    assert client.get("/api/config").json() == {"passcode": False, "daily_cap": 0}


@pytest.mark.parametrize("n", [0, 1, 7, 41])
def test_too_few_or_too_many_photos_are_refused_with_the_range(client, n):
    r = client.post("/api/scans", files=photos(n)) if n else client.post("/api/scans")
    assert r.status_code in (400, 422)
    if n:
        assert "8 to 40" in r.json()["detail"] and not client.started


def test_eight_photos_start_a_scan(client):
    r = client.post("/api/scans", files=photos(8))
    assert r.status_code == 200 and len(client.started) == 1
    sid = r.json()["id"]
    st = client.get(f"/api/scans/{sid}").json()
    assert st["state"] == "queued" and st["photos"] == 8 and st["files"] == []


@pytest.mark.parametrize("name", ["notes.txt", "drawing.pdf", "anim.gif", "photo"])
def test_files_that_are_not_photos_are_refused_by_name(client, name):
    files = photos(7) + [("photos", (name, io.BytesIO(b"hello"), "application/octet-stream"))]
    r = client.post("/api/scans", files=files)
    assert r.status_code == 400 and name in r.json()["detail"]


@pytest.mark.parametrize("name", ["IMG_{:02d}.HEIC", "IMG_{:02d}.png", "IMG_{:02d}.JPEG"])
def test_iphone_and_other_photo_types_are_taken(client, name):
    assert client.post("/api/scans", files=photos(8, name)).status_code == 200


def test_the_passcode_is_checked_before_anything_else(client, monkeypatch):
    monkeypatch.setattr(server, "PASSCODE", "Sheet-1234")
    assert client.get("/api/config").json()["passcode"] is True
    assert client.post("/api/scans", files=photos(8)).status_code == 401
    assert client.post("/api/scans", files=photos(8), headers={"x-passcode": "wrong"}).status_code == 401
    r = client.post("/api/scans", files=photos(8), headers={"x-passcode": " sheet-1234 "})     # case and spaces forgiven
    assert r.status_code == 200 and len(client.started) == 1


def test_the_daily_cap_stops_runs_and_says_when(client, monkeypatch):
    monkeypatch.setattr(server, "DAILY_CAP", 2)
    assert client.post("/api/scans", files=photos(8)).status_code == 200
    assert client.post("/api/scans", files=photos(8)).status_code == 200
    r = client.post("/api/scans", files=photos(8))
    assert r.status_code == 429 and "tomorrow" in r.json()["detail"] and len(client.started) == 2
    # A refused upload (too few photos) does not use up a run.
    monkeypatch.setattr(server, "DAILY_CAP", 3)
    assert client.post("/api/scans", files=photos(3)).status_code == 400
    assert client.post("/api/scans", files=photos(8)).status_code == 200


@pytest.mark.parametrize("sid", ["nope", "../../etc", "A" * 80, "abc def"])
def test_unknown_or_malformed_scan_ids_are_404(client, sid):
    assert client.get(f"/api/scans/{sid}").status_code == 404


def test_only_listed_files_can_be_downloaded(client, tmp_path):
    sid = client.post("/api/scans", files=photos(8)).json()["id"]
    res = tmp_path / sid / "result"; res.mkdir(parents=True)
    (res / "model.step").write_text("ISO-10303-21;")
    (res / "summary.json").write_text("{}")
    assert client.get(f"/api/scans/{sid}/files/model.step").status_code == 200
    for name in ("summary.json", "..%2Fstatus.json", "../status.json", "views.pkl"):
        assert client.get(f"/api/scans/{sid}/files/{name}").status_code == 404, name
    assert client.get(f"/api/scans/{sid}/files/holder.step").status_code == 404     # listed, not made yet
    assert [f["name"] for f in client.get(f"/api/scans/{sid}").json()["files"]] == ["model.step"]


def test_the_agent_needs_a_scan_with_photos_and_the_passcode(client, monkeypatch):
    sid = client.post("/api/scans", files=photos(8)).json()["id"]
    assert client.post(f"/api/scans/{sid}/agent").status_code == 404                 # no photos posed yet
    monkeypatch.setattr(server, "PASSCODE", "x")
    assert client.post(f"/api/scans/{sid}/agent").status_code == 401


def test_examples_are_listed_by_title(client, tmp_path):
    d = tmp_path / "example-gear"; d.mkdir()
    (d / "status.json").write_text(json.dumps({"state": "done", "title": "Gear"}))
    (tmp_path / "abcdef123456").mkdir()
    assert client.get("/api/examples").json() == [{"id": "example-gear", "name": "Gear"}]


def test_the_page_and_the_sheet_load(client):
    page = client.get("/")
    assert page.status_code == 200 and "Photos in" in page.text
    sheet = client.get("/sheet.pdf")
    assert sheet.status_code == 200 and sheet.content[:4] == b"%PDF"


def test_our_refusals_read_as_written_and_anything_else_is_ours():
    assert server.friendly(ValueError("Take them from all the way round.")) == "Take them from all the way round."
    assert "on our side" in server.friendly(KeyError("rv"))
    assert "on our side" in server.friendly(RuntimeError("cuda"))


@pytest.mark.parametrize("target, says", [("sleepy", "took too long"), ("crashy", "stopped unexpectedly")])
def test_a_scan_that_hangs_or_crashes_ends_itself_not_the_server(tmp_path, monkeypatch, target, says):
    from tests import _children
    monkeypatch.setattr(server, "SCANS", str(tmp_path))
    (tmp_path / "abcd1234").mkdir()
    server._status("abcd1234", state="queued")
    t = time.time()
    server._work("abcd1234", [], target=getattr(_children, target), timeout=3)
    st = json.load(open(tmp_path / "abcd1234" / "status.json"))
    assert st["state"] == "failed" and says in st["error"] and time.time() - t < 30, st
    assert server.lock.acquire(timeout=1)                 # the next scan is not blocked
    server.lock.release()
