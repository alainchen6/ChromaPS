#!/usr/bin/env python3
"""Run the fixed-point pipeline on real photographs.

The data is the Harvard photometric stereo set [1]: seven figurines, each
captured under 20 calibrated directional lights, with recovered normals as
ground truth.  Three of the 20 frames are stacked into one RGB image, so the
chip sees exactly what it would see from a colour-multiplexed capture.

    curl -O http://vision.seas.harvard.edu/qsfs/PSData.zip    # 117 MB
    unzip PSData.zip
    python3 model/real.py --data PSData/cat --out stim/real

[1] Harvard QSFS photometric stereo dataset,
    http://vision.seas.harvard.edu/qsfs/Data.html
"""
import argparse
import json
import os
import sys

import numpy as np
import scipy.io as sio
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
import golden  # noqa: E402
from render import write_cfg, q13, q14  # noqa: E402

DEFAULT_LIGHTS = (3, 10, 17)


def load(data_dir, lights):
    L = np.loadtxt(os.path.join(data_dir, "refined_light.txt"), delimiter=",")  # 3 x 20
    idx = [i - 1 for i in lights]
    imgs = [np.asarray(Image.open(os.path.join(data_dir, f"Image_{i:02d}.png")))
            for i in lights]
    rgb = np.stack(imgs, -1)                      # H x W x 3, uint8

    mat = sio.loadmat(os.path.join(data_dir, "result.mat"))
    # the .mat stores rows bottom-up relative to the images
    rho_gt = mat["rho"][::-1]
    n_gt = mat["n"][::-1]
    mask = (rho_gt > 1e-6) & (np.linalg.norm(np.nan_to_num(n_gt), axis=-1) > 0.5)
    n_gt = np.nan_to_num(n_gt)
    return rgb, L[:, idx].T, n_gt, mask


def meta_for(L3, w, h):
    A = np.linalg.inv(L3)
    # two virtual lights for the relight outputs: a key light and a rim light
    lv = []
    for az, el in ((-35.0, 35.0), (135.0, 30.0)):
        a, e = np.deg2rad(az), np.deg2rad(el)
        lv.append([np.sin(e) * np.cos(a), np.sin(e) * np.sin(a), np.cos(e)])
    return {
        "scene": "real",
        "rig": "world",
        "width": w,
        "height": h,
        "exposure": 1.0,
        "noise": 0.0,
        "specular": 0.0,
        "vignette": 0.0,
        "texture": 0.0,
        "a_q13": [[q13(v) for v in row] for row in A],
        "wb_q8": [256, 256, 256],
        "light_q14": [[q14(v) for v in row] for row in lv],
        "thresh": {"low": 4, "sat": 251, "mag": 2048},
        "lights_q13": [[q13(v) for v in row] for row in L3],
    }


def figure(rgb, n_gt, n_ours, relit, mask, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bg = "#131110"
    fig, axs = plt.subplots(1, 4, figsize=(13.6, 4.0), dpi=130)
    fig.patch.set_facecolor(bg)
    def shaded(n):
        img = np.clip(n * 0.5 + 0.5, 0, 1)
        img[~mask] = (0.07, 0.062, 0.055)
        return img

    cap = rgb / 255.0
    cap[~mask] = (0.07, 0.062, 0.055)

    panels = [
        (cap, "capture: three lights in R, G, B"),
        (shaded(n_gt), "ground truth normals"),
        (shaded(n_ours), "this chip, fixed point"),
        (np.stack([relit / 255.0] * 3, -1), "re-lit by a virtual lamp"),
    ]
    for ax, (img, title) in zip(axs, panels):
        ax.imshow(np.clip(img, 0, 1))
        ax.set_title(title, fontsize=10, pad=6, color="#a29a8c")
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color("#3a352f")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", transparent=True)
    print("wrote", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="directory with Image_XX.png")
    ap.add_argument("--out", default="stim/real")
    ap.add_argument("--lights", nargs=3, type=int, default=list(DEFAULT_LIGHTS))
    args = ap.parse_args()

    rgb, L3, n_gt, mask = load(args.data, args.lights)
    h, w, _ = rgb.shape
    meta = meta_for(L3, w, h)

    out = os.path.join(ROOT, args.out)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    write_cfg(os.path.join(out, "cfg.hex"), meta)

    flat = rgb.reshape(-1, 3)
    with open(os.path.join(out, "frame.hex"), "w") as f:
        f.write("\n".join(f"{r:02x}{g:02x}{b:02x}" for r, g, b in flat))
        f.write("\n")

    def write_ppm(path, arr):
        with open(path, "wb") as f:
            f.write(f"P6\n{w} {h}\n255\n".encode())
            f.write(arr.astype(np.uint8).tobytes())

    write_ppm(os.path.join(out, "frame.ppm"), rgb)
    np.save(os.path.join(out, "gt_normal.npy"), n_gt.astype(np.float32))
    np.save(os.path.join(out, "mask.npy"), mask)

    normal8, albedo8, relights, conf, rho, n = golden.run(
        (flat[:, 0], flat[:, 1], flat[:, 2]), meta)

    n_ours = (normal8.reshape(h, w, 3).astype(np.float64) - 128.0) / 127.0
    n_ours /= np.maximum(np.linalg.norm(n_ours, axis=-1, keepdims=True), 1e-9)

    d = np.clip(np.einsum("ijk,ijk->ij", n_ours, n_gt), -1, 1)
    ang = np.degrees(np.arccos(d))[mask]
    ang_float = np.degrees(np.arccos(np.clip(
        np.einsum("ijk,ijk->ij",
                  (lambda g: g / np.linalg.norm(g, axis=-1, keepdims=True))(
                      (rgb.reshape(-1, 3) / 255.0) @ np.linalg.inv(L3).T).reshape(h, w, 3),
                  n_gt), -1, 1)))[mask]

    print(f"{args.data}: {w}x{h}, {mask.mean()*100:.1f}% object, "
          f"{(conf == 0).mean()*100:.1f}% low confidence")
    print(f"float least squares : median {np.median(ang_float):5.2f}  mean {ang_float.mean():5.2f}")
    print(f"this chip (8-bit)   : median {np.median(ang):5.2f}  mean {ang.mean():5.2f}"
          f"  p95 {np.percentile(ang, 95):5.2f}")

    figure(rgb, n_gt, n_ours, relights[0].reshape(h, w), mask,
           os.path.join(ROOT, "docs/img/case_real.png"))

    out_dir = os.path.join(ROOT, "out")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "real_report.json"), "w") as f:
        json.dump({"median": float(np.median(ang)), "mean": float(ang.mean()),
                   "p95": float(np.percentile(ang, 95)),
                   "low_conf_frac": float((conf == 0).mean()),
                   "lights": list(args.lights)}, f, indent=2)


if __name__ == "__main__":
    main()
