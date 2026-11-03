"""Minimal SAM 3.1 client over the Meta Model API, parsed with Meta's own parser."""
import asyncio, base64, io, json, os
import numpy as np, requests
from PIL import Image
import meta_sam_parser as msp

BASE = os.environ.get("MODEL_API_BASE", "https://api.meta.ai/v1")
KEY = os.environ.get("MODEL_API_KEY", "")

def load_scaled(path, max_side):
    im = Image.open(path).convert("RGB")
    s = min(1.0, max_side / max(im.size))
    if s < 1:
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    return im, s

def _events(body):
    with requests.post(BASE + "/responses", headers={"Authorization": "Bearer " + KEY},
                       json=body, stream=True, timeout=300) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if line and line.startswith("data:"):
                data = line[5:].strip()
                if data and data != "[DONE]":
                    yield json.loads(data)

async def _aiter(events):
    for e in events:
        yield e

async def _parse(events):
    parsed = msp.parse_responses_stream(_aiter(events), msp.image_segmentation_format())
    return await parsed.final_result()

def segment(path, prompt, max_side=1536):
    """Returns (image, scale, records) with records: dict(box, conf, mask HxW bool at image size)."""
    im, s = load_scaled(path, max_side)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=92)
    url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    body = {"model": "sam-3.1", "stream": True,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": url}]}],
            "metadata": {"include_confidence": "true"}}
    events = list(_events(body))
    result = asyncio.run(_parse(events))
    boxes, masks = {}, {}
    for rec in result.records:
        if rec.kind == "box":
            boxes[rec.object_id] = rec
        elif rec.kind == "mask":
            masks[rec.object_id] = rec
    out = []
    for oid, b in boxes.items():
        r = {"box": (b.left, b.top, b.right, b.bottom), "conf": b.confidence}
        if oid in masks:
            mr = masks[oid]; m = mr.mask
            crop = np.frombuffer(msp.decode_mask_to_raster(m), dtype=np.uint8).reshape(m.height, m.width)
            full = np.zeros((im.height, im.width), dtype=bool)
            bx = mr.bounds  # the mask is the crop inside its bounds; large ones arrive downsampled
            x0, y0 = int(bx.left), int(bx.top)
            bw = min(int(bx.right) - x0 + 1, im.width - x0); bh = min(int(bx.bottom) - y0 + 1, im.height - y0)
            if crop.shape != (bh, bw):
                crop = np.array(Image.fromarray(crop * 255).resize((bw, bh), Image.BILINEAR)) > 127
            full[y0:y0 + bh, x0:x0 + bw] = crop.astype(bool)
            r["mask"] = full
        out.append(r)
    return im, s, out
