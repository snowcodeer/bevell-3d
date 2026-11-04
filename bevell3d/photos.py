"""Photos in one frame: HEIC converted, EXIF rotation applied, scaled to a working size.

Masks, markers and cameras must all agree on the pixel frame, and OpenCV and Pillow
disagree about EXIF rotation, so every photo is baked upright once and saved as JPEG.
"""
import json, os, shutil, subprocess, tempfile
from PIL import Image, ImageOps

MAX_SIDE = 1536


def _open(path):
    if path.lower().endswith((".heic", ".heif")):
        try:                                     # Linux (the deployed app): pillow-heif
            import pillow_heif
            pillow_heif.register_heif_opener()
            return Image.open(path)
        except ImportError:                      # macOS without it: sips
            pass
        tmp = tempfile.mkdtemp()
        out = os.path.join(tmp, "photo.jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", path, "--out", out], check=True, capture_output=True)
        im = Image.open(out); im.load(); shutil.rmtree(tmp)
        return im
    return Image.open(path)


def prepare(paths, out_dir, max_side=MAX_SIDE):
    """Returns [(name, working_path, full_path)] in the order given. The working copy is at most
    `max_side`; the full one keeps every pixel, for finding small, far-off markers.
    A photo that cannot be read (cut off mid-upload, not really an image) is left out and
    named in `unreadable.json`; the scan goes on with the rest, and stops with a reason only
    when none can be read."""
    os.makedirs(os.path.join(out_dir, "full"), exist_ok=True)
    out, unreadable = [], []
    for p in paths:
        name = os.path.splitext(os.path.basename(p))[0]
        dst = os.path.join(out_dir, name + ".jpg")
        full = os.path.join(out_dir, "full", name + ".jpg")
        if not (os.path.exists(dst) and os.path.exists(full)):
            try:
                im = ImageOps.exif_transpose(_open(p)).convert("RGB")
                im.load()
            except Exception as e:                       # OSError for a truncated file, and so on
                unreadable.append({"photo": os.path.basename(p), "why": f"{type(e).__name__}: {e}"[:160]})
                continue
            im.save(full, "JPEG", quality=95)
            s = min(1.0, max_side / max(im.size))
            if s < 1:
                im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
            im.save(dst, "JPEG", quality=95)
        out.append((name, dst, full))
    json.dump(unreadable, open(os.path.join(out_dir, "unreadable.json"), "w"), indent=1)
    if not out:
        raise ValueError("None of the photos could be opened. Send JPEG, PNG or HEIC photos straight from the camera.")
    return out
