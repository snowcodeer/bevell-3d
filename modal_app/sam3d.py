"""Meta's SAM 3D Objects on a Modal GPU: one photo and its object mask in, a mesh out.

The mesh comes in SAM 3D's own frame and scale; `bevell3d.fit` puts it at true size on the
sheet. Weights are gated (facebook/sam-3d-objects): the Modal secret `huggingface` holds a
read token for an account with access, and the first run copies them into a Volume.

    modal run modal_app/sam3d.py::check_image                 # build and test the environment
    modal run modal_app/sam3d.py --image photo.jpg --mask mask.png --out object.glb
"""
import io, os, sys
import modal

SAM3D_COMMIT = "f91db411c50efee93d8db7aeb323885650f6f722"     # main on 2 Jun 2026
PYTORCH3D = "git+https://github.com/facebookresearch/pytorch3d.git@75ebeeaea0908c5527e7b1e305fbc7681382db47"
GPU = os.environ.get("SAM3D_GPU", "L40S")                      # needs 32 GB or more

app = modal.App("bevell-sam3d")
weights = modal.Volume.from_name("bevell-sam3d-weights", create_if_missing=True)

image = (
    modal.Image.from_registry("nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04", add_python="3.11")
    .apt_install("git", "wget", "build-essential", "ninja-build", "libgl1", "libglib2.0-0", "libegl1",
                 "libgles2", "libxrender1", "libxi6", "libxkbcommon0", "libsm6", "libxext6")
    # SAM 3D's setup also lists pypi.ngc.nvidia.com, which no longer resolves (3 Nov 2026).
    .env({"PIP_EXTRA_INDEX_URL": "https://download.pytorch.org/whl/cu121",
          "TORCH_CUDA_ARCH_LIST": "8.0;8.6;8.9;9.0", "FORCE_CUDA": "1", "MAX_JOBS": "8"})
    .run_commands(f"git clone https://github.com/facebookresearch/sam-3d-objects /opt/sam3d && "
                  f"cd /opt/sam3d && git checkout {SAM3D_COMMIT}")
    .run_commands("pip install --upgrade pip wheel 'setuptools<75' packaging ninja")
    # nvidia-pyindex only points pip at that dead index, and its build fails, so it goes.
    .run_commands("cd /opt/sam3d && sed -i '/^nvidia-pyindex/d' requirements.txt && pip install -r requirements.txt")
    # Modal's Python was built with clang and asks for clang++, which this image lacks.
    .env({"CC": "gcc", "CXX": "g++", "LDSHARED": "gcc -pthread -shared", "LDCXXSHARED": "g++ -pthread -shared"})
    # Both compile against the torch installed above, so no build isolation.
    .run_commands(f"pip install --no-build-isolation '{PYTORCH3D}'", gpu=GPU)
    .run_commands("pip install --no-build-isolation flash_attn==2.8.3", gpu=GPU)
    .env({"PIP_FIND_LINKS": "https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.5.1_cu121.html"})
    .run_commands("cd /opt/sam3d && pip install --no-build-isolation -r requirements.inference.txt", gpu=GPU)
    .run_commands("cd /opt/sam3d && pip install --no-deps -e . && python patching/hydra")
    .pip_install("huggingface_hub[cli]<1.0", "trimesh")
    # The notebook's loader skips the package's init (LIDRA_SKIP_INIT) and takes CUDA_HOME from
    # CONDA_PREFIX, which only exists in their conda setup.
    .env({"HF_HOME": "/weights/hf-cache", "PYTHONPATH": "/opt/sam3d/notebook", "LIDRA_SKIP_INIT": "true",
          "CONDA_PREFIX": "/usr/local/cuda", "CUDA_HOME": "/usr/local/cuda"})
)

hf_secret = [modal.Secret.from_name("huggingface")] if os.environ.get("HF_SECRET", "1") == "1" else []


@app.function(image=image, gpu=GPU, timeout=600)
def check_image():
    """Imports every compiled dependency on a GPU, without weights."""
    import torch, pytorch3d, kaolin, gsplat, flash_attn, sam3d_objects   # noqa: F401
    return {"torch": str(torch.__version__), "cuda": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0), "pytorch3d": str(pytorch3d.__version__), "kaolin": str(kaolin.__version__)}


def _ensure_weights():
    cfg = "/weights/checkpoints/hf/pipeline.yaml"
    if not os.path.exists(cfg):
        import shutil, subprocess
        subprocess.run(["hf", "download", "--repo-type", "model", "--local-dir", "/weights/download",
                        "--max-workers", "1", "facebook/sam-3d-objects"], check=True)
        os.makedirs("/weights/checkpoints", exist_ok=True)
        shutil.move("/weights/download/checkpoints", "/weights/checkpoints/hf")
        shutil.rmtree("/weights/download", ignore_errors=True)
        weights.commit()
    return cfg


@app.cls(image=image, gpu=GPU, volumes={"/weights": weights}, secrets=hf_secret, timeout=900, scaledown_window=120)
class Sam3D:
    @modal.enter()
    def load(self):
        sys.path.append("/opt/sam3d/notebook")
        from inference import Inference
        self.inference = Inference(_ensure_weights(), compile=False)

    @modal.method()
    def reconstruct(self, image_bytes: bytes, mask_png: bytes, seed: int = 42) -> dict:
        import numpy as np
        from PIL import Image
        img = np.array(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
        mask = np.array(Image.open(io.BytesIO(mask_png)).convert("L")) > 127
        out = self.inference(img, mask, seed=seed)
        glb = out.get("glb")
        if glb is None:
            raise RuntimeError(f"no mesh in the output (keys: {sorted(out)})")
        pose = {k: out[k].detach().cpu().numpy().tolist() for k in ("rotation", "translation", "scale") if k in out}
        return {"glb": glb.export(file_type="glb"), "pose": pose}


@app.local_entrypoint()
def main(image: str, mask: str, out: str = "object.glb", seed: int = 42):
    res = Sam3D().reconstruct.remote(open(image, "rb").read(), open(mask, "rb").read(), seed)
    open(out, "wb").write(res["glb"])
    print("saved", out, "pose", res["pose"])
