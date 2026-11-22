#!/usr/bin/env python3
"""Build the comparison figure from the RTL simulation outputs and print the
quality numbers (angle error against the ray-traced ground truth)."""
import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_ppm(path):
    with open(path, "rb") as f:
        assert f.readline().strip() == b"P6"
        w, h = map(int, f.readline().split())
        assert int(f.readline()) == 255
        return np.frombuffer(f.read(), dtype=np.uint8).reshape(h, w, 3)


def main():
    stim = os.path.join(ROOT, "stim")
    out = os.path.join(ROOT, "out")
    with open(os.path.join(stim, "meta.json")) as f:
        meta = json.load(f)

    src = read_ppm(os.path.join(stim, "frame.ppm"))
    normal = read_ppm(os.path.join(out, "rtl_normal.ppm"))
    albedo = read_ppm(os.path.join(out, "rtl_albedo.ppm"))
    rel0 = read_ppm(os.path.join(out, "rtl_relight0.ppm"))

    # RTL normal map -> unit vectors, compare with the ray-traced truth
    gt = np.load(os.path.join(stim, "gt_normal.npy"))
    nv = normal.astype(np.float64) / 255.0 * 2.0 - 1.0
    nv /= np.maximum(np.linalg.norm(nv, axis=-1, keepdims=True), 1e-9)
    ang = np.degrees(np.arccos(np.clip(np.sum(nv * gt, axis=-1), -1, 1)))
    conf = np.loadtxt(os.path.join(out, "rtl_conf.hex"), dtype=str)
    conf = conf.reshape(meta["height"], meta["width"])
    good = conf == "ff"
    print(f"pixels                 : {ang.size}")
    print(f"low confidence         : {(~good).sum()} ({(~good).mean()*100:.1f}%)")
    print(f"angle error (conf=255) : mean {ang[good].mean():.3f} deg, "
          f"p95 {np.percentile(ang[good], 95):.3f} deg")
    warn = (ang > 10) & good
    print(f"conf=255 but >10 deg   : {warn.sum()}")

    fig, axs = plt.subplots(2, 2, figsize=(11, 8), dpi=110)
    panel = [
        (src, "1. INPUT - one shot under R/G/B lights"),
        (normal, "2. RTL output - surface normal"),
        (albedo, "3. RTL output - albedo"),
        (rel0, "4. RTL output - relit by a virtual light"),
    ]
    for ax, (img, title) in zip(axs.ravel(), panel):
        ax.imshow(img)
        ax.set_title(title, fontsize=10.5, pad=6)
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color("#999")
    fig.suptitle("ChromaPS RTL simulation - 320x240, 76800 pixels, bit-exact vs model",
                 fontsize=12)
    plt.tight_layout()
    fig.savefig(os.path.join(out, "demo.png"), bbox_inches="tight")
    print(f"wrote {out}/demo.png")


if __name__ == "__main__":
    main()
