#!/usr/bin/env python3
"""Drop a real photograph into the pipeline.

Two ways to shoot it:

  single shot   one photo taken under red, green and blue LEDs at the same time
                (this is what the chip is built for)
  three shots   three photos of the same object, each lit by one coloured light;
                the script merges them into the RGB frame the chip expects

The calibration matrix A is the default rig; pass --calib with nine Q2.13
integers if your light directions differ.

    python3 model/photo.py --single IMG_0042.jpg --out stim/mine
    python3 model/photo.py --triple red.jpg green.jpg blue.jpg --out stim/mine

Writes stim/<name>/{frame.hex,frame.ppm,meta.json,cfg.hex} and, for a quick
look, out/<name>_{normal,albedo,relight0}.png.
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
import golden  # noqa: E402
from render import write_cfg, world_rig, q13, q14  # noqa: E402


def default_meta(w, h, calib=None):
    L = world_rig(30.0, (0.0, 120.0, 240.0))
    A = np.linalg.inv(L)
    a_q13 = [[q13(v) for v in row] for row in A]
    if calib:
        vals = [int(x) for x in calib.split(",")]
        assert len(vals) == 9, "--calib needs nine integers"
        a_q13 = [vals[0:3], vals[3:6], vals[6:9]]
    return {
        "scene": "photo",
        "rig": "world",
        "width": w,
        "height": h,
        "exposure": 1.0,
        "noise": 0.0,
        "specular": 0.0,
        "vignette": 0.0,
        "texture": 0.0,
        "a_q13": a_q13,
        "wb_q8": [256, 256, 256],
        "light_q14": [[q14(v) for v in world_rig(40.0, (az,))[0]] for az in (-50.0, 70.0)],
        "thresh": {"low": 4, "sat": 251, "mag": 2048},
        "lights_q13": [[q13(v) for v in row] for row in L],
    }


def load(path, w, h):
    im = Image.open(path).convert("RGB")
    iw, ih = im.size
    s = max(w / iw, h / ih)
    im = im.resize((max(w, int(iw * s + 0.5)), max(h, int(ih * s + 0.5))), Image.LANCZOS)
    iw, ih = im.size
    left, top = (iw - w) // 2, (ih - h) // 2
    return im.crop((left, top, left + w, top + h))


def write_ppm(path, arr):
    h, w, _ = arr.shape
    with open(path, "wb") as f:
        f.write(f"P6\n{w} {h}\n255\n".encode())
        f.write(arr.astype(np.uint8).tobytes())


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--single", help="one photo under simultaneous R/G/B light")
    g.add_argument("--triple", nargs=3, metavar=("R", "G", "B"),
                   help="three photos, one per coloured light")
    ap.add_argument("--out", default=os.path.join("stim", "photo"))
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--height", type=int, default=240)
    ap.add_argument("--calib", default=None)
    args = ap.parse_args()

    w, h = args.width, args.height
    if args.single:
        img = np.asarray(load(args.single, w, h))
    else:
        chans = [np.asarray(load(p, w, h).convert("L")) for p in args.triple]
        img = np.stack(chans, -1)

    out = os.path.join(ROOT, args.out)
    os.makedirs(out, exist_ok=True)

    meta = default_meta(w, h, args.calib)
    with open(os.path.join(out, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    write_cfg(os.path.join(out, "cfg.hex"), meta)
    write_ppm(os.path.join(out, "frame.ppm"), img)

    flat = img.reshape(-1, 3)
    with open(os.path.join(out, "frame.hex"), "w") as f:
        f.write("\n".join(f"{r:02x}{g:02x}{b:02x}" for r, g, b in flat))
        f.write("\n")
    np.save(os.path.join(out, "gt_normal.npy"), np.zeros((h, w, 3), np.float32))
    np.save(os.path.join(out, "mask.npy"), np.ones((h, w), bool))

    # a quick look without waiting for the RTL
    normal8, albedo8, relights, conf, _, _ = golden.run(
        (flat[:, 0], flat[:, 1], flat[:, 2]), meta)
    name = os.path.basename(out.rstrip("/"))
    dst = os.path.join(ROOT, "out")
    os.makedirs(dst, exist_ok=True)
    write_ppm(os.path.join(dst, f"{name}_normal.ppm"),
              normal8.reshape(h, w, 3))
    write_ppm(os.path.join(dst, f"{name}_albedo.ppm"),
              np.stack([albedo8.reshape(h, w)] * 3, -1))
    write_ppm(os.path.join(dst, f"{name}_relight0.ppm"),
              np.stack([relights[0].reshape(h, w)] * 3, -1))

    print(f"{args.out}: {w}x{h}, {(conf == 0).mean()*100:.1f}% low confidence")
    print(f"wrote {out}/ and out/{name}_*.ppm")


if __name__ == "__main__":
    sys.exit(main())
