#!/usr/bin/env python3
"""Directed edge-case stimulus: saturation, shadow, zero signal, weak signal."""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import world_rig, q13, q14, write_cfg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 8, 4

PIXELS = [
    (0, 0, 0),        # no signal at all
    (255, 255, 255),  # saturated in all three channels
    (255, 0, 0),      # red only: two channels in shadow
    (200, 200, 200),  # nominal
    (4, 4, 4),        # at the low threshold
    (5, 5, 5),        # just above the low threshold, weak
    (250, 250, 250),  # just below saturation
    (251, 251, 251),  # at saturation
    (221, 221, 221),  # flat surface, unit albedo
    (128, 128, 128),  # half exposure
    (255, 255, 0),    # blue in shadow
    (0, 255, 255),
    (60, 200, 30),    # arbitrary colour
    (13, 200, 201),
    (200, 13, 201),
    (17, 19, 23),
]


def main():
    L = world_rig(30.0, (0.0, 120.0, 240.0))
    A = np.linalg.inv(L)
    meta = {
        "scene": "edge",
        "rig": "world",
        "width": W,
        "height": H,
        "exposure": 1.0,
        "noise": 0.0,
        "a_q13": [[q13(v) for v in row] for row in A],
        "wb_q8": [256, 256, 256],
        "light_q14": [[q14(v) for v in world_rig(40.0, (az,))[0]] for az in (-50.0, 70.0)],
        "thresh": {"low": 4, "sat": 251, "mag": 2048},
        "lights_q13": [[q13(v) for v in row] for row in L],
    }

    out = os.path.join(ROOT, "stim", "edge")
    os.makedirs(out, exist_ok=True)

    rows = [PIXELS[i % len(PIXELS)] for i in range(W * H)]
    with open(os.path.join(out, "frame.hex"), "w") as f:
        f.write("\n".join(f"{r:02x}{g:02x}{b:02x}" for r, g, b in rows))
        f.write("\n")

    with open(os.path.join(out, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    np.save(os.path.join(out, "gt_normal.npy"), np.zeros((H, W, 3), np.float32))
    write_cfg(os.path.join(out, "cfg.hex"), meta)
    print(f"edge: {W}x{H} -> {out}")


if __name__ == "__main__":
    sys.exit(main())
