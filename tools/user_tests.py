"""What users will do to the photos, run through the real pipeline.

Starting from a good rendered scan, each scenario changes the photo set the way a person might
(too few, blurred, dark, tiny, huge, rotated, PNG, HEIC, one side only, the same photo again
and again, no sheet in view, a broken file, two objects mixed). A scenario passes when the scan
either comes out at the right size or fails with a message a person can act on. A crash with
a programmer's error, or a wrong size reported as a success, fails it.

    .venv/bin/python -m tools.user_tests [--base out/bench/bottle/full/photos] [--only blur]

Writes out/usertests/report.json and prints a table.
"""
import argparse, glob, json, os, shutil, time, traceback
import numpy as np
from PIL import Image, ImageFilter

OUT = "out/usertests"
TRUE_MM = {"bottle": (62.0, 61.8, 110.5)}            # the vitamin bottle's true size, from its scan


def _save(img, path, fmt=None, **kw):
    img.save(path, fmt, **kw)
    return path


def scenarios(base, other):
    """name -> (what it imitates, builder(out_dir) -> photo paths, expectation)."""
    photos = sorted(glob.glob(os.path.join(base, "*.jpg")))
    imgs = lambda: [(os.path.basename(p), Image.open(p).convert("RGB")) for p in photos]

    def each(fn, ext=".jpg", fmt="JPEG", **kw):
        def build(d):
            return [_save(fn(im), os.path.join(d, os.path.splitext(n)[0] + ext), fmt, **kw) for n, im in imgs()]
        return build

    def subset(idx):
        return lambda d: [shutil.copy(photos[i], d) for i in idx]

    def rotated_exif(d):
        out = []
        for n, im in imgs():
            exif = Image.Exif(); exif[0x0112] = 6                      # display rotated 90 degrees clockwise
            out.append(_save(im.transpose(Image.Transpose.ROTATE_90), os.path.join(d, n), "JPEG", exif=exif, quality=92))
        return out

    def heic(d):
        import pillow_heif
        pillow_heif.register_heif_opener()
        return [_save(im, os.path.join(d, os.path.splitext(n)[0] + ".heic"), "HEIF", quality=90) for n, im in imgs()]

    def no_sheet(d):
        out = []
        for n, im in imgs():                                           # keep the middle third: object, no squares
            w, h = im.size
            out.append(_save(im.crop((w // 3, h // 3, 2 * w // 3, 2 * h // 3)), os.path.join(d, n), "JPEG", quality=92))
        return out

    def broken_file(d):
        out = [shutil.copy(p, d) for p in photos]
        data = open(out[3], "rb").read(); open(out[3], "wb").write(data[: len(data) // 3])
        return out

    def duplicates(d):
        return [shutil.copy(photos[0], os.path.join(d, f"IMG_{i:02d}.jpg")) for i in range(16)]

    def mixed(d):
        others = sorted(glob.glob(os.path.join(other, "*.jpg")))
        out = [shutil.copy(p, os.path.join(d, "A_" + os.path.basename(p))) for p in photos[::2]]
        return out + [shutil.copy(p, os.path.join(d, "B_" + os.path.basename(p))) for p in others[1::2]]

    return {
        "minimum_8": ("the fewest photos the app takes", subset([0, 2, 4, 6, 8, 10, 12, 14]), "size"),
        "one_side": ("8 photos all from one side", subset([0, 1, 2, 6, 7, 8, 9, 14]), "size or reason"),
        "blurred": ("shaky hands: every photo blurred", each(lambda im: im.filter(ImageFilter.GaussianBlur(3)), quality=92), "size or reason"),
        "dark": ("a dim room", each(lambda im: Image.eval(im, lambda v: int(v * 0.35)), quality=92), "size or reason"),
        "tiny_640": ("photos shrunk to 640 px by a messaging app", each(lambda im: im.resize((640, int(640 * im.height / im.width))), quality=85), "size or reason"),
        "huge_48mp": ("a 48 MP phone camera", each(lambda im: im.resize((8064, 6048), Image.Resampling.BICUBIC), quality=90), "size"),
        "rotated_exif": ("portrait photos rotated by their EXIF tag", rotated_exif, "size"),
        "png": ("screenshots saved as PNG", each(lambda im: im, ".png", "PNG"), "size"),
        "heic": ("straight off an iPhone, HEIC", heic, "size"),
        "duplicates": ("the same photo sixteen times", duplicates, "reason"),
        "no_sheet": ("cropped so the sheet's squares are gone", no_sheet, "reason"),
        "broken_file": ("one photo cut off mid-download", broken_file, "size or reason"),
        "mixed_objects": ("photos of two different objects", mixed, "reason"),
    }


def readable(msg):
    """A message a person can act on, not a programmer's error."""
    bad = ("Traceback", "KeyError", "IndexError", "NoneType", "AttributeError", "ZeroDivision", "TypeError", "not subscriptable")
    return bool(msg) and not any(b in msg for b in bad)


def run_one(name, what, build, expect, true_mm):
    from bevell3d.run import run
    d = os.path.join(OUT, name); shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "photos")); os.makedirs(os.path.join(d, "result"))
    paths = sorted(build(os.path.join(d, "photos")))
    t = time.time(); row = {"scenario": name, "imitates": what, "expect": expect, "photos": len(paths)}
    try:
        s = run(paths, os.path.join(d, "result"), use_sam3d=False, log=lambda *a: None)
        size = sorted(s["model_mm"])
        off = max(abs(a - b) for a, b in zip(size, sorted(true_mm)))
        row.update(outcome="made", model_mm=s["model_mm"], off_mm=round(off, 1), posed=s.get("scan", {}).get("posed"),
                   issues=s["plan"].get("photo_issues"), cad=s.get("cad", {}).get("kind"))
        # A success must be the right size; a wrong size passed off as success is the worst case.
        row["pass"] = off <= 4.0 and expect != "reason"
        if expect == "reason" and off <= 4.0:
            row["pass"] = True                                         # it coped after all: fine
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        row.update(outcome="refused", message=msg[:300], pass_=None)
        row["pass"] = expect != "size" and readable(str(e)) and type(e).__name__ in ("ValueError", "RuntimeError")
        row["trace_tail"] = traceback.format_exc().strip().splitlines()[-3:]
    row["seconds"] = round(time.time() - t, 1)
    return row


def main(base, other, only=None):
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for name, (what, build, expect) in scenarios(base, other).items():
        if only and only not in name:
            continue
        row = run_one(name, what, build, expect, TRUE_MM["bottle"])
        rows.append(row)
        print(("PASS " if row["pass"] else "FAIL ") + name.ljust(14), row["outcome"].ljust(8),
              (f"off {row['off_mm']} mm, {row.get('posed')} posed, CAD {row.get('cad')}" if row["outcome"] == "made" else row["message"][:110]),
              f"({row['seconds']} s)", flush=True)
        json.dump(rows, open(os.path.join(OUT, "report.json"), "w"), indent=1, default=str)
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="out/bench/bottle/full/photos")
    ap.add_argument("--other", default="out/bench/mario/timed/photos")
    ap.add_argument("--only")
    a = ap.parse_args()
    main(a.base, a.other, a.only)
