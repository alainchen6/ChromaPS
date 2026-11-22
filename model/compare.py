#!/usr/bin/env python3
"""Compare two hex dumps (one line per pixel) and report mismatches."""
import argparse
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path, nibbles):
    with open(path) as f:
        return np.array([int(line.strip(), 16) for line in f if line.strip()],
                        dtype=np.int64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="golden")
    ap.add_argument("--b", default="rtl")
    ap.add_argument("--ppm", action="store_true", help="also write PPMs of the b-side")
    args = ap.parse_args()

    out = os.path.join(ROOT, "out")
    channels = [("normal", 6), ("albedo", 2), ("relight0", 2),
                ("relight1", 2), ("conf", 2)]
    total_bad = 0
    for name, nibbles in channels:
        pa = os.path.join(out, f"{args.a}_{name}.hex")
        pb = os.path.join(out, f"{args.b}_{name}.hex")
        if not (os.path.exists(pa) and os.path.exists(pb)):
            print(f"{name:9s}  SKIP (missing file)")
            continue
        a = load(pa, nibbles)
        b = load(pb, nibbles)
        if a.shape != b.shape:
            print(f"{name:9s}  LENGTH MISMATCH {a.shape} vs {b.shape}")
            total_bad += 1
            continue
        bad = a != b
        nbad = int(bad.sum())
        total_bad += nbad
        if nbad:
            idx = np.flatnonzero(bad)[:5]
            print(f"{name:9s}  {nbad}/{a.size} mismatches, first:", end=" ")
            print(", ".join(f"px{int(i)}: {int(a[i]):x} vs {int(b[i]):x}" for i in idx))
        else:
            print(f"{name:9s}  OK  ({a.size} pixels)")

    if args.ppm:
        import json
        with open(os.path.join(ROOT, "stim", "meta.json")) as f:
            meta = json.load(f)
        w, h = meta["width"], meta["height"]
        norm = np.stack([load(os.path.join(out, f"{args.b}_normal.hex"), 6) >> 16 & 0xFF,
                         load(os.path.join(out, f"{args.b}_normal.hex"), 6) >> 8 & 0xFF,
                         load(os.path.join(out, f"{args.b}_normal.hex"), 6) & 0xFF], -1)
        alb = load(os.path.join(out, f"{args.b}_albedo.hex"), 2)
        rel = load(os.path.join(out, f"{args.b}_relight0.hex"), 2)
        for name, img in [("normal", norm), ("albedo", np.stack([alb] * 3, -1)),
                          ("relight0", np.stack([rel] * 3, -1))]:
            with open(os.path.join(out, f"{args.b}_{name}.ppm"), "wb") as f:
                f.write(f"P6\n{w} {h}\n255\n".encode())
                f.write(np.asarray(img, dtype=np.uint8).tobytes())
        print(f"wrote {args.b}_normal/albedo/relight0.ppm")

    print("RESULT:", "PASS" if total_bad == 0 else f"FAIL ({total_bad} mismatching pixels)")
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
