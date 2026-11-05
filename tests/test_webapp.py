"""The web app's API as a user (or a curious judge) would poke at it, without starting a scan."""
import io, json, os, sys, time, types
import pytest
from fastapi.testclient import TestClient
import webapp.server as server

JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")   # a tiny JPEG-shaped file
KEY = "test-key-123"                                                     # a visitor's own Meta Model API key


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "SCANS", str(tmp_path))
    monkeypatch.setattr(server, "PASSCODE", "")
    monkeypatch.setattr(server, "DAILY_CAP", 0)
    monkeypatch.setattr(server, "BYOK_DAILY_CAP", 200)
    monkeypatch.setattr(server, "BYOK_SAM3D", True)
    monkeypatch.setattr(server, "UNLIMITED_DAILY_CAP", 20)
    monkeypatch.setattr(server, "_verdicts", {})
    monkeypatch.setattr(server, "_ask_bevell", lambda key: pytest.fail("asked the real bevell.app"))
    started, agents = [], []
    monkeypatch.setattr(server, "_work", lambda scan_id, paths, key=None, sam3d=True: started.append((scan_id, paths, key, sam3d)))
    monkeypatch.setattr(server, "_agent", lambda scan_id, key=None: agents.append((scan_id, key)))
    monkeypatch.setattr(server.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda self: target(*args)})())
    c = TestClient(server.app)
    c.started, c.agents = started, agents
    return c


def photos(n, name="IMG_{:02d}.jpg"):
    return [("photos", (name.format(i), io.BytesIO(JPEG), "image/jpeg")) for i in range(n)]


def test_open_by_default_and_says_so(client):
    assert client.get("/api/config").json() == {"passcode": False, "daily_cap": 0, "byok": True, "byok_daily_cap": 200,
                                                "unlimited": True, "unlimited_daily_cap": 20}


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


# ---------- a visitor's own Meta Model API key ----------

def own(key=KEY):
    return {"x-model-api-key": key}


class Refused(Exception):
    """What requests raises when the Meta Model API turns a key down, quoting it as an API might."""
    response = types.SimpleNamespace(status_code=401)


def test_with_a_passcode_set_no_passcode_and_no_key_is_refused(client, monkeypatch):
    monkeypatch.setattr(server, "PASSCODE", "Sheet-1234")
    r = client.post("/api/scans", files=photos(8))
    assert r.status_code == 401 and "own Meta Model API key" in r.json()["detail"] and not client.started


def test_an_own_key_alone_is_let_in_and_handed_to_the_run_in_memory(client, monkeypatch):
    monkeypatch.setattr(server, "PASSCODE", "Sheet-1234")
    r = client.post("/api/scans", files=photos(8), headers=own())
    assert r.status_code == 200 and client.started[0][0] == r.json()["id"] and client.started[0][2] == KEY
    # The passcode still lets a run in on its own, on our key.
    assert client.post("/api/scans", files=photos(8), headers={"x-passcode": "sheet-1234"}).status_code == 200
    assert client.started[1][2] is None


@pytest.mark.parametrize("key", ["test key 123", "test-key-123\t", "x" * 513, "short", b"t\xe9st-key-123"])
def test_a_malformed_key_is_refused_before_anything_runs(client, monkeypatch, key):
    monkeypatch.setattr(server, "BYOK_DAILY_CAP", 1)
    r = client.post("/api/scans", files=photos(8), headers=own(key))
    assert r.status_code == 400 and "doesn't look right" in r.json()["detail"] and not client.started
    assert client.post("/api/scans", files=photos(8), headers=own()).status_code == 200      # no run was used up


def test_the_key_is_never_written_down_or_sent_back(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "PASSCODE", "Sheet-1234")
    r = client.post("/api/scans", files=photos(8), headers=own())
    sid, bodies = r.json()["id"], [r.text]
    (tmp_path / sid / "result").mkdir()
    (tmp_path / sid / "result" / "views.pkl").write_bytes(b"")
    for r in (client.get(f"/api/scans/{sid}"), client.post(f"/api/scans/{sid}/agent", headers=own()),
              client.get(f"/api/scans/{sid}"), client.get("/api/config"), client.get("/api/examples")):
        assert r.status_code == 200
        bodies.append(r.text)
    assert client.agents == [(sid, KEY)]                 # the agent request brings its own, in memory
    assert not any(KEY in b for b in bodies)
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert {"status.json", "_usage.json"} <= {p.name for p in written}
    assert not any(KEY.encode() in p.read_bytes() for p in written)


def test_own_key_runs_have_a_cap_of_their_own(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "PASSCODE", "Sheet-1234")
    monkeypatch.setattr(server, "DAILY_CAP", 1)
    monkeypatch.setattr(server, "BYOK_DAILY_CAP", 2)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    (tmp_path / "_usage.json").write_text(json.dumps({"2026-01-01": 9, "own-key 2026-01-01": 9}))   # old days go
    ours = {"x-passcode": "sheet-1234"}
    assert client.post("/api/scans", files=photos(8), headers=ours).status_code == 200
    assert client.post("/api/scans", files=photos(8), headers=ours).status_code == 429        # ours are used up
    assert client.post("/api/scans", files=photos(8), headers=own()).status_code == 200       # theirs are not
    assert client.post("/api/scans", files=photos(8), headers=own()).status_code == 200
    r = client.post("/api/scans", files=photos(8), headers=own())
    assert r.status_code == 429 and "own keys" in r.json()["detail"] and "tomorrow" in r.json()["detail"]
    assert json.loads((tmp_path / "_usage.json").read_text()) == {today: 1, f"own-key {today}": 2}
    assert len(client.started) == 3 and client.get("/api/config").json()["byok_daily_cap"] == 2


def test_sam3d_runs_on_an_own_key_unless_turned_off(client, monkeypatch):
    client.post("/api/scans", files=photos(8), headers=own())
    monkeypatch.setattr(server, "BYOK_SAM3D", False)
    client.post("/api/scans", files=photos(8), headers=own())
    client.post("/api/scans", files=photos(8))                                                  # ours keeps it
    assert [(k, s) for _, _, k, s in client.started] == [(KEY, True), (KEY, False), (None, True)]


def test_config_says_an_own_key_works_beside_the_passcode(client, monkeypatch):
    monkeypatch.setattr(server, "PASSCODE", "Sheet-1234")
    c = client.get("/api/config").json()
    assert c["passcode"] is True and c["byok"] is True and "Sheet" not in json.dumps(c)


def test_an_own_key_turned_down_by_the_api_is_said_to_be_theirs():
    assert "turned your key down" in server.friendly(Refused("401"), own_key=True)
    assert "on our side" in server.friendly(Refused("401"))         # on our key, that is ours to fix


@pytest.fixture
def child(tmp_path, capsys, monkeypatch):
    """A run's own process, run here: everything it sets is put back afterwards."""
    monkeypatch.setattr(server, "SCANS", str(tmp_path))
    monkeypatch.setattr(server, "_SECRET", "")
    monkeypatch.setenv("MODEL_API_KEY", "our-key-0000")
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    sam = types.ModuleType("bevell3d.sam_client"); sam.KEY = "our-key-0000"      # as if imported already
    monkeypatch.setitem(sys.modules, "bevell3d.sam_client", sam)
    (tmp_path / "abcd1234" / "result").mkdir(parents=True)
    server._status("abcd1234", state="queued", mode="scan")
    return tmp_path / "abcd1234", sam, capsys


def fake_module(name, **funcs):
    """A bevell3d module that notes what MODEL_API_KEY was when the import reached it."""
    m = types.ModuleType(name); m.seen = {}

    def reached(attr):
        if attr not in funcs:
            raise AttributeError(attr)
        m.seen["env"] = os.environ.get("MODEL_API_KEY")
        return funcs[attr]
    m.__getattr__ = reached
    return m


def test_the_scan_child_runs_on_the_key_and_masks_it_everywhere(child, monkeypatch):
    folder, sam, capsys = child
    got = {}

    def run(paths, out, log, progress, tool, use_sam3d):
        got.update(env=os.environ["MODEL_API_KEY"], sam3d=use_sam3d)
        progress("plan", f"asking with {KEY}")
        json.dump({"sam3d_error": f"Bearer {KEY}"}, open(os.path.join(out, "summary.json"), "w"))
        print("calling the API with", KEY)
        raise Refused(f"401 Unauthorized: invalid key {KEY!r}")
    mod = fake_module("bevell3d.run", run=run)
    monkeypatch.setitem(sys.modules, "bevell3d.run", mod)
    server._scan_child("abcd1234", [], str(folder.parent), KEY, False)
    assert mod.seen["env"] == KEY and got == {"env": KEY, "sam3d": False} and sam.KEY == KEY
    st = json.load(open(folder / "status.json"))
    assert st["state"] == "failed" and "turned your key down" in st["error"] and "*" * len(KEY) in st["error_detail"]
    printed = capsys.readouterr()
    assert "Refused" in printed.err and "calling the API with" in printed.out      # printed, masked
    assert KEY not in printed.out + printed.err
    assert not any(KEY.encode() in p.read_bytes() for p in folder.rglob("*") if p.is_file())


def test_the_agent_child_runs_on_its_own_key_and_masks_it(child, monkeypatch):
    folder, sam, capsys = child
    shown = []

    def run_agent(res, rounds, log):
        log(f"Muse Spark: bad key {KEY}")
        shown.append((folder / "status.json").read_text())
        raise Refused(f"Bearer {KEY}")
    mod = fake_module("bevell3d.agent_cad", run_agent=run_agent)
    monkeypatch.setitem(sys.modules, "bevell3d.agent_cad", mod)
    server._agent_child("abcd1234", str(folder.parent), KEY)
    st = json.load(open(folder / "status.json"))
    assert mod.seen["env"] == KEY and st["agent"]["state"] == "failed" and "your key" in st["agent"]["error"]
    assert "bad key" in shown[0] and KEY not in shown[0] + json.dumps(st) + "".join(capsys.readouterr())


def test_the_key_reaches_a_spawned_run_as_an_argument_and_goes_no_further(tmp_path, monkeypatch, capfd):
    from tests import _children
    monkeypatch.setattr(server, "SCANS", str(tmp_path))
    (tmp_path / "abcd1234").mkdir()
    server._status("abcd1234", state="queued")
    server._work("abcd1234", [], key=KEY, sam3d=False, target=_children.keyed, timeout=60)
    st = json.load(open(tmp_path / "abcd1234" / "status.json"))
    assert st["got_key"] is True and st["sam3d"] is False and "*" * len(KEY) in st["echo"], st
    assert os.environ.get("MODEL_API_KEY") != KEY                         # this process never had it
    printed = capfd.readouterr()
    assert "calling the API with" in printed.out and KEY not in printed.out + printed.err
    assert not any(KEY.encode() in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


# ---------- a Bevell Unlimited subscriber's Bevell API key ----------

BVL = "bvl_test_abc123"


def bevell(monkeypatch, status=200, sub="active", account="acct-1", error=None):
    """bevell.app's GET /api/v1/account, answering as told; counts how often it is asked."""
    asked = []

    def ask(key):
        asked.append(key)
        if error:
            raise error
        body = {"object": "account", "id": account, "email": "someone@example.com", "subscription": {"status": sub}}
        return types.SimpleNamespace(status_code=status, json=lambda: body)
    monkeypatch.setattr(server, "_ask_bevell", ask)
    return asked


def test_an_unlimited_bevell_key_runs_on_our_meta_key_and_is_kept_nowhere(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "PASSCODE", "Sheet-1234")
    asked = bevell(monkeypatch, sub="trialing")
    r = client.post("/api/scans", files=photos(8), headers=own(BVL))
    assert r.status_code == 200 and asked == [BVL]
    assert client.started[0][2:] == (None, True)          # our Meta key, SAM 3D on; the Bevell key not passed
    sid, bodies = r.json()["id"], [r.text]
    (tmp_path / sid / "result").mkdir()
    (tmp_path / sid / "result" / "views.pkl").write_bytes(b"")
    for r in (client.post(f"/api/scans/{sid}/agent", headers=own(BVL)), client.get(f"/api/scans/{sid}")):
        assert r.status_code == 200
        bodies.append(r.text)
    assert client.agents == [(sid, None)] and len(asked) == 1        # the verdict was kept, not asked again
    today = time.strftime("%Y-%m-%d", time.gmtime())
    assert json.loads((tmp_path / "_usage.json").read_text()) == {f"unlimited acct-1 {today}": 2}
    assert not any(BVL in b for b in bodies) and BVL not in json.dumps({k: str(v) for k, v in server._verdicts.items()})
    assert not any(BVL.encode() in p.read_bytes() or b"someone@" in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


@pytest.mark.parametrize("status, sub, code, says", [
    (200, "canceled", 402, "no Bevell Unlimited"), (200, None, 402, "no Bevell Unlimited"),
    (402, None, 402, "no Bevell Unlimited"), (401, None, 401, "not recognised"), (500, None, 503, "Could not check")])
def test_a_bevell_key_without_unlimited_is_refused_and_says_why(client, monkeypatch, status, sub, code, says):
    bevell(monkeypatch, status=status, sub=sub)
    r = client.post("/api/scans", files=photos(8), headers=own(BVL))
    assert r.status_code == code and says in r.json()["detail"] and BVL not in r.text and not client.started


def test_a_bevell_check_that_times_out_is_a_503_and_is_asked_again(client, monkeypatch):
    import requests
    asked = bevell(monkeypatch, error=requests.Timeout(f"read timed out for {BVL}"))
    for _ in range(2):
        r = client.post("/api/scans", files=photos(8), headers=own(BVL))
        assert r.status_code == 503 and "Could not check your Bevell subscription" in r.json()["detail"] and BVL not in r.text
    assert len(asked) == 2 and not client.started             # a failed check is not kept


def test_bevell_verdicts_are_kept_ten_minutes_by_hash(client, monkeypatch):
    asked = bevell(monkeypatch)
    assert client.post("/api/scans", files=photos(8), headers=own(BVL)).status_code == 200
    assert client.post("/api/scans", files=photos(8), headers=own(BVL)).status_code == 200
    assert len(asked) == 1 and list(server._verdicts) == [server.hashlib.sha256(BVL.encode()).hexdigest()]
    (h, (until, account)), = server._verdicts.items()
    assert account == "acct-1" and 590 < until - time.time() <= 600
    server._verdicts[h] = (time.time() - 1, account)                   # ten minutes on: asked again
    assert client.post("/api/scans", files=photos(8), headers=own(BVL)).status_code == 200 and len(asked) == 2


def test_each_unlimited_account_has_its_own_daily_cap(client, monkeypatch):
    monkeypatch.setattr(server, "UNLIMITED_DAILY_CAP", 1)
    bevell(monkeypatch, account="acct-1")
    assert client.post("/api/scans", files=photos(8), headers=own(BVL)).status_code == 200
    r = client.post("/api/scans", files=photos(8), headers=own(BVL))
    assert r.status_code == 429 and "Bevell Unlimited" in r.json()["detail"]
    bevell(monkeypatch, account="acct-2")
    assert client.post("/api/scans", files=photos(8), headers=own("bvl_other_key_2")).status_code == 200


def _finished_gripper_run(tmp_path, sid="srcgripper01", created=1.0, clip=True):
    res = tmp_path / sid / "result"
    res.mkdir(parents=True)
    for n in ("custom_jaws.3mf", "custom_moving_jaw.stl", "model.step") + (("custom_jaws_sim_three_quarter.mp4",) if clip else ()):
        (res / n).write_bytes(b"x")
    (tmp_path / sid / "status.json").write_text(json.dumps({"state": "done", "mode": "gripper", "created": created,
                                                             "summary": {"custom_jaws": {"sim": {"gripper_max_deg": 25.8}}},
                                                             "plan": {"object": "black scissors"}}))
    return sid


def test_a_demo_upload_replays_the_newest_finished_gripper_run_without_counting(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DEMO_PACE", 0.0)
    monkeypatch.setattr(server, "DAILY_CAP", 1)
    _finished_gripper_run(tmp_path, "oldgripper01", created=1.0)
    src = _finished_gripper_run(tmp_path, "newgripper01", created=2.0)
    _finished_gripper_run(tmp_path, "noclipgrip01", created=3.0, clip=False)       # newer, but no MuJoCo clip
    for _ in range(2):                                                                 # a cap of 1 is not used up
        r = client.post("/api/scans", files=photos(11), data={"mode": "gripper", "demo": "1"})
        assert r.status_code == 200
    st = client.get(f"/api/scans/{r.json()['id']}").json()
    assert st["state"] == "done" and st["demo_of"] == src and st["photos"] == 11
    assert {"custom_jaws.3mf", "custom_jaws_sim_three_quarter.mp4"} <= {f["name"] for f in st["files"]}
    assert st["summary"]["custom_jaws"]["sim"]["gripper_max_deg"] == 25.8 and "grippers" in st["done"]
    assert not client.started                                                          # no real run, no model


def test_without_demo_a_gripper_upload_is_a_normal_run(client, tmp_path):
    _finished_gripper_run(tmp_path)
    r = client.post("/api/scans", files=photos(11), data={"mode": "gripper"})
    assert r.status_code == 200 and len(client.started) == 1
    assert "demo_of" not in client.get(f"/api/scans/{r.json()['id']}").json()


def test_a_demo_needs_no_passcode_but_a_real_run_still_does(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DEMO_PACE", 0.0)
    monkeypatch.setattr(server, "PASSCODE", "Sheet-1234")
    _finished_gripper_run(tmp_path, "newgripper01", created=2.0)
    r = client.post("/api/scans", files=photos(11), data={"mode": "gripper", "demo": "1"})
    assert r.status_code == 200 and not client.started
    assert client.post("/api/scans", files=photos(11), data={"mode": "gripper"}).status_code == 401
    monkeypatch.setattr(server, "DEMO_DAILY_CAP", 1)
    assert client.post("/api/scans", files=photos(11), data={"mode": "gripper", "demo": "1"}).status_code == 429


def test_a_demo_stores_no_photos_and_needs_only_the_count(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DEMO_PACE", 0.0)
    _finished_gripper_run(tmp_path, "newgripper01", created=2.0)
    r = client.post("/api/scans", data={"mode": "gripper", "demo": "1", "count": "11"})
    assert r.status_code == 200
    sid = r.json()["id"]
    st = client.get(f"/api/scans/{sid}").json()
    assert st["state"] == "done" and st["photos"] == 11 and st["demo_of"] == "newgripper01"
    assert not (tmp_path / sid / "upload").exists()


def _finished_scan_run(tmp_path, sid, created=1.0, extra=None):
    res = tmp_path / sid / "result"
    res.mkdir(parents=True)
    for n in ("model.step", "model.stl", "holder.3mf"):
        (res / n).write_bytes(b"x")
    st = {"state": "done", "mode": "scan", "created": created, "summary": {"model_mm": [96.6, 75.0, 29.9]},
          "plan": {"object": "peach mounting bracket"}}
    st.update(extra or {})
    (tmp_path / sid / "status.json").write_text(json.dumps(st))
    return sid


def test_a_scan_demo_replays_the_newest_real_scan_without_a_login(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DEMO_PACE", 0.0)
    monkeypatch.setattr(server, "PASSCODE", "Sheet-1234")
    _finished_scan_run(tmp_path, "oldscan00001", created=1.0)
    src = _finished_scan_run(tmp_path, "newscan00001", created=2.0)
    _finished_scan_run(tmp_path, "demoscan0001", created=3.0, extra={"demo_of": "oldscan00001"})   # a replay is never a source
    _finished_gripper_run(tmp_path, "gripper00001", created=4.0)                                     # nor a gripper run
    r = client.post("/api/scans", data={"mode": "scan", "demo": "1", "count": "11"})
    assert r.status_code == 200 and not client.started
    st = client.get(f"/api/scans/{r.json()['id']}").json()
    assert st["state"] == "done" and st["demo_of"] == src and st["mode"] == "scan" and st["photos"] == 11
    assert "grippers" not in st["done"] and "cad" in st["done"]
    assert {"model.step", "model.stl", "holder.3mf"} <= {f["name"] for f in st["files"]}
    assert client.post("/api/scans", files=photos(11), data={"mode": "scan"}).status_code == 401   # a real run still needs access


def test_a_scan_demo_falls_back_to_the_bracket_example(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DEMO_PACE", 0.0)
    _finished_scan_run(tmp_path, "example-bracket", created=1.0)
    r = client.post("/api/scans", data={"mode": "scan", "demo": "1", "count": "11"})
    assert r.status_code == 200
    assert client.get(f"/api/scans/{r.json()['id']}").json()["demo_of"] == "example-bracket"
