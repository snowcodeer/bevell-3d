"""The Bevell 3D web app on Modal: the same FastAPI server as locally, with Blender for the
smooth NURBS step, scans in a Volume, and SAM 3D called on the bevell-sam3d GPU app.

    modal secret create bevell-3d-meta --from-dotenv path/to/meta.env
    modal secret create bevell-3d-access BEVELL3D_PASSCODE=<passcode>
    modal deploy modal_app/web.py
    modal volume put bevell-3d-scans out/scans/example-bottle /example-bottle    # each example

A scan or a CAD agent run needs the passcode, and there are BEVELL3D_DAILY_CAP of them a day.
Or the visitor's own Meta Model API key, with its own cap (BEVELL3D_BYOK_DAILY_CAP, default 200).
One container serves everything: the server runs one scan at a time and keeps its state on
disk, so a second container would only split the queue.
"""
import os, threading
import modal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BLENDER = "https://download.blender.org/release/Blender5.0/blender-5.0.1-linux-x64.tar.xz"   # the version tested locally

app = modal.App("bevell-3d")
scans = modal.Volume.from_name("bevell-3d-scans", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.12")
    # OpenCV, OpenCascade and Blender's own libraries; Blender runs headless (-b).
    .apt_install("wget", "xz-utils", "libgl1", "libglu1-mesa", "libegl1", "libglib2.0-0", "libx11-6", "libxi6",
                 "libxrender1", "libxkbcommon0", "libsm6", "libxext6", "libxxf86vm1", "libxfixes3", "libgomp1")
    .run_commands(f"wget -q {BLENDER} -O /tmp/blender.tar.xz && mkdir -p /opt/blender && "
                  "tar -xJf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 && rm /tmp/blender.tar.xz && "
                  "/opt/blender/blender -b --version | head -1")
    .pip_install_from_requirements(os.path.join(ROOT, "requirements.txt"))
    .env({"BLENDER": "/opt/blender/blender", "BEVELL3D_SCANS": "/scans", "BEVELL3D_DAILY_CAP": "50"})
    .add_local_dir(os.path.join(ROOT, "bevell3d"), "/root/bevell3d")
    .add_local_dir(os.path.join(ROOT, "webapp"), "/root/webapp")
    .add_local_dir(os.path.join(ROOT, "assets"), "/root/assets")
    .add_local_dir(os.path.join(ROOT, "third_party"), "/root/third_party")     # the SO-101 gripper, for the scissors simulation
)


@app.function(image=image, volumes={"/scans": scans}, cpu=4, memory=8192, timeout=3600,
              secrets=[modal.Secret.from_name("bevell-3d-meta"), modal.Secret.from_name("bevell-3d-access")],
              max_containers=1, scaledown_window=1200)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def web():
    # Writes to a Volume reach other containers and later deploys only once committed.
    def keep():
        while True:
            threading.Event().wait(15)
            try:
                scans.commit()
            except Exception:
                pass
    threading.Thread(target=keep, daemon=True).start()
    from webapp.server import app as fastapi_app
    return fastapi_app
