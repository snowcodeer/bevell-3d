"""Stand-ins for the pipeline, run in a spawned process by tests/test_webapp.py."""
import json, os, sys, time


def sleepy(scan_id, paths, scans_dir, key=None, sam3d=True):
    time.sleep(60)


def crashy(scan_id, paths, scans_dir, key=None, sam3d=True):
    os._exit(3)                                   # as a crash in native code would end it


def keyed(scan_id, paths, scans_dir, key=None, sam3d=True):
    """Takes the key as the scan's child does, says what it got, and prints the key."""
    import webapp.server as server
    server.SCANS = scans_dir
    server._use_key(key)
    print("calling the API with", key, flush=True)
    print("Bearer", key, file=sys.stderr, flush=True)
    server._status(scan_id, state="done", got_key=os.environ.get("MODEL_API_KEY") == key, sam3d=sam3d,
                   echo=f"401: invalid key {key}")
    json.dump({"error": f"Bearer {key}"}, open(os.path.join(scans_dir, scan_id, "echo.json"), "w"))
    server._sweep(os.path.join(scans_dir, scan_id))
