#!/usr/bin/env python3
"""Cut a small window out of the full stimulus, for the gate-level short run."""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N = 64
R0, C0 = 88, 128


def main():
    with open(os.path.join(ROOT, "stim", "meta.json")) as f:
        meta = json.load(f)
    W, H = meta["width"], meta["height"]
    with open(os.path.join(ROOT, "stim", "frame.hex")) as f:
        px = [line.strip() for line in f if line.strip()]

    assert R0 + N <= H and C0 + N <= W
    crop = []
    for r in range(R0, R0 + N):
        crop += px[r * W + C0: r * W + C0 + N]

    with open(os.path.join(ROOT, "stim", "slice.hex"), "w") as f:
        f.write("\n".join(crop))
        f.write("\n")

    meta = dict(meta)
    meta["width"] = N
    meta["height"] = N
    with open(os.path.join(ROOT, "stim", "slice_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    gt = np.load(os.path.join(ROOT, "stim", "gt_normal.npy"))
    np.save(os.path.join(ROOT, "stim", "slice_gt.npy"), gt[R0:R0 + N, C0:C0 + N])
    print(f"stim/slice.hex  {N}x{N} from ({R0},{C0})")


if __name__ == "__main__":
    sys.exit(main())
