"""Copy SAM 3D Objects' gated weights into the Volume `sam3d.py` reads, on a CPU container.

Its own app, so it runs while the GPU image is still building.

    modal run modal_app/sam3d_weights.py
"""
import modal

app = modal.App("bevell-sam3d-weights")
weights = modal.Volume.from_name("bevell-sam3d-weights", create_if_missing=True)
image = modal.Image.debian_slim(python_version="3.11").pip_install("huggingface_hub[cli]<1.0", "hf_transfer")


@app.function(image=image, volumes={"/weights": weights}, secrets=[modal.Secret.from_name("huggingface")],
              timeout=3600, cpu=4)
def download():
    import os, shutil, subprocess
    cfg = "/weights/checkpoints/hf/pipeline.yaml"
    if os.path.exists(cfg):
        return "already there"
    subprocess.run(["hf", "download", "--repo-type", "model", "--local-dir", "/weights/download",
                    "facebook/sam-3d-objects"], check=True, env={**os.environ, "HF_HUB_ENABLE_HF_TRANSFER": "1"})
    os.makedirs("/weights/checkpoints", exist_ok=True)
    shutil.move("/weights/download/checkpoints", "/weights/checkpoints/hf")
    shutil.rmtree("/weights/download", ignore_errors=True)
    weights.commit()
    out = subprocess.run(["du", "-sh", "/weights/checkpoints/hf"], capture_output=True, text=True).stdout
    return sorted(os.listdir("/weights/checkpoints/hf")), out.strip()


@app.local_entrypoint()
def main():
    print(download.remote())
