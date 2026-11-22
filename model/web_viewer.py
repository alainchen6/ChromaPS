#!/usr/bin/env python3
"""Bake the data the interactive relight viewer needs.

Per case we store normal + albedo as one RGBA buffer

    R,G,B = normal encoded as (n * 127 + 128)
    A     = albedo

and write it to docs/img/light/<case>.js as window.LIGHT[<case>] = {w,h,d}
with d = base64 of the buffer, instead of a PNG. Reason: a canvas that has
drawn a file:// image is tainted, so getImageData() throws when the page is
opened straight from disk. A <script> tag is not subject to that.

Also writes one *_thumb.png per case, shaded by I = albedo * max(0, n . l),
the same identity the page evaluates per frame.

    python3 model/web_viewer.py --out docs/img/light
"""
import argparse
import base64
import json
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
import golden  # noqa: E402

CASES = ["plate", "sphere", "bumps", "studio", "real"]
W, H = 320, 240


def load_case(name):
    d = os.path.join(ROOT, "stim", name)
    with open(os.path.join(d, "meta.json")) as f:
        meta = json.load(f)
    with open(os.path.join(d, "frame.hex")) as f:
        vals = [int(x.strip(), 16) for x in f if x.strip()]
    v = np.array(vals, dtype=np.int64)
    img = ((v >> 16) & 255, (v >> 8) & 255, v & 255)
    return img, meta


def fit(arr, w, h):
    """centre-crop to 4:3 then resize to (w, h)."""
    im = Image.fromarray(arr)
    iw, ih = im.size
    target = w / h
    if iw / ih > target:
        nw = int(ih * target)
        im = im.crop(((iw - nw) // 2, 0, (iw + nw) // 2, ih))
    else:
        nh = int(iw / target)
        im = im.crop((0, (ih - nh) // 2, iw, (ih + nh) // 2))
    return np.asarray(im.resize((w, h), Image.LANCZOS))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("docs", "img", "light"))
    args = ap.parse_args()
    out = os.path.join(ROOT, args.out)
    os.makedirs(out, exist_ok=True)

    for name in CASES:
        img, meta = load_case(name)
        normal8, albedo8, relights, conf, rho, n = golden.run(img, meta)
        w, h = meta["width"], meta["height"]
        nrm = normal8.reshape(h, w, 3).astype(np.uint8)
        alb = albedo8.reshape(h, w).astype(np.uint8)

        nrm = fit(nrm, W, H)
        alb = fit(alb, W, H)

        rgba = np.dstack([nrm, alb])
        b64 = base64.b64encode(rgba.tobytes()).decode("ascii")
        with open(os.path.join(out, f"{name}.js"), "w") as f:
            f.write('window.LIGHT=window.LIGHT||{};window.LIGHT["%s"]={w:%d,h:%d,d:"%s"};\n'
                    % (name, W, H, b64))

        # thumbnail: same shading the page opens with
        nf = (nrm.astype(np.float32) - 128.0) / 127.0
        nf /= np.maximum(np.linalg.norm(nf, axis=-1, keepdims=True), 1e-6)
        az, el = np.deg2rad(-50), np.deg2rad(32)
        l = np.array([np.sin(el) * np.cos(az), np.sin(el) * np.sin(az), np.cos(el)], np.float32)
        shade = np.clip(np.einsum("ijk,k->ij", nf, l), 0, None) * (alb.astype(np.float32) / 255.0)
        thumb = (np.clip(shade, 0, 1) * 255).astype(np.uint8)
        Image.fromarray(np.dstack([thumb] * 3)).save(os.path.join(out, f"{name}_thumb.png"), optimize=True)
        print(f"{name}: {w}x{h} -> {W}x{H}", os.path.getsize(os.path.join(out, f"{name}.js")))


if __name__ == "__main__":
    main()
