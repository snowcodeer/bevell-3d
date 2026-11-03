"""Muse Spark plans the scan: what to ask SAM 3.1 for, and which way to rebuild the object.

It makes choices only. Every dimension comes from the photos and the sheet, never from
the model.
"""
import base64, io, json, os
import requests
from PIL import Image, ImageOps

BASE = os.environ.get("MODEL_API_BASE", "https://api.meta.ai/v1")
MODEL = os.environ.get("PLANNER_MODEL", "muse-spark-1.3")

ROUTES = {
    "flat": "a thin plate or sheet part, under about 6 mm thick, whose outline is what matters "
            "(a medal, gasket, washer, bracket plate, coaster). Rebuilt as its outline extruded.",
    "revolved": "turned about one vertical axis, round in every horizontal slice (a bottle, cup, "
                "knob, jar, lens cap). Rebuilt from its profile.",
    "freeform": "anything else (a phone, earbuds case, tool, toy, remote). Rebuilt in 3D from "
                "the photos and a generated shape fitted to them.",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "object": {"type": "string", "description": "2 to 5 words naming the object so a segmentation "
                   "model finds it and nothing else, colour first, e.g. 'dark blue earbuds case'"},
        "route": {"type": "string", "enum": list(ROUTES)},
        "reason": {"type": "string", "description": "one short sentence"},
        "photo_issues": {"type": "array", "items": {"type": "string"},
                         "description": "problems that will hurt the scan, e.g. a hand in shot, the "
                         "object off the sheet, no photos from near the table; empty if none"},
    },
    "required": ["object", "route", "reason", "photo_issues"],
    "additionalProperties": False,
}

PROMPT = (
    "These photos show one object on a printed sheet with black square markers round its edge. "
    "We will cut the object out of every photo with a segmentation model and rebuild it in 3D at "
    "true size from the sheet, then print a holder for it.\n\nChoose:\n"
    + "\n".join(f"- {k}: {v}" for k, v in ROUTES.items())
    + "\n\nName the object as a segmentation prompt: what it is, with its colour, never the sheet, "
    "the markers, the table or a hand. Do not estimate any size."
)


def _data_url(path, max_side=1024):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def plan(photo_paths, max_photos=3, key=None):
    key = key or os.environ["MODEL_API_KEY"]
    picks = photo_paths[:: max(1, len(photo_paths) // max_photos)][:max_photos]
    content = [{"type": "text", "text": PROMPT}] + \
              [{"type": "image_url", "image_url": {"url": _data_url(p)}} for p in picks]
    body = {"model": MODEL, "max_tokens": 4000,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "scan_plan", "strict": True, "schema": SCHEMA}}}
    r = requests.post(BASE + "/chat/completions", headers={"Authorization": "Bearer " + key}, json=body, timeout=180)
    r.raise_for_status()
    out = json.loads(r.json()["choices"][0]["message"]["content"])
    if out.get("route") not in ROUTES:
        out["route"] = "freeform"
    return out


if __name__ == "__main__":
    import sys
    print(json.dumps(plan(sys.argv[1:]), indent=1))
