"""BevellBridge: a Fusion 360 add-in that lets Bevell build a model in the open Fusion and read
the result back, so the Fusion side of a feature tree can be tested end to end.

POST http://127.0.0.1:47822/build  {"script": <a Bevell model script>, "close": true}
  runs the script's build() on Fusion's main thread, without dialogs, and answers with its
  report: errors per step, the timeline, the user parameters and each body's volume and size.
GET  http://127.0.0.1:47822/       health check.

Only 127.0.0.1 can reach it. It runs only scripts Bevell wrote (they define build()).
"""
import json, queue, threading, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler

import adsk.core

PORT = 47822
EVENT_ID = "bevell_bridge_build"
_app = None
_server = None
_handlers = []
_jobs = queue.Queue()


class _OnMainThread(adsk.core.CustomEventHandler):
    def notify(self, args):
        while not _jobs.empty():
            job = _jobs.get_nowait()
            try:
                ns = {"__name__": "bevell_model"}
                exec(compile(job["script"], "<bevell model>", "exec"), ns)
                job["result"] = ns["build"](None, close=job.get("close", True))
            except Exception:
                job["result"] = {"fatal": traceback.format_exc()[-2000:]}
            job["done"].set()


class _Http(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _reply(self, obj):
        data = json.dumps(obj, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._reply({"ok": True, "fusion": _app.version if _app else None})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        job = {"script": body.get("script", ""), "close": body.get("close", True), "done": threading.Event()}
        _jobs.put(job)
        _app.fireCustomEvent(EVENT_ID, "")
        self._reply(job["result"] if job["done"].wait(300) else {"fatal": "Fusion did not finish within 300 s"})


def run(context):
    global _app, _server
    try:
        _app = adsk.core.Application.get()
        event = _app.registerCustomEvent(EVENT_ID)
        handler = _OnMainThread()
        event.add(handler)
        _handlers.append(handler)
        _server = HTTPServer(("127.0.0.1", PORT), _Http)
        threading.Thread(target=_server.serve_forever, daemon=True).start()
    except Exception:
        adsk.core.Application.get().userInterface.messageBox("BevellBridge could not start:\n" + traceback.format_exc())


def stop(context):
    try:
        if _server:
            _server.shutdown()
            _server.server_close()
        if _app:
            _app.unregisterCustomEvent(EVENT_ID)
    except Exception:
        pass
