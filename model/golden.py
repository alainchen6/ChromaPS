#!/usr/bin/env python3
"""Bit-exact fixed-point model of the ChromaPS datapath.

Every operation below matches the RTL cycle-for-cycle in value (not in time):
same widths, same rounding, same saturation.  This file is the reference the
RTL simulation is compared against.

Fixed-point contract
--------------------
I_k      uint8
wb_k     uint10  Q2.8     (256 == 1.0)
I'_k     uint10           min(1023, (I_k * wb_k) >> 8)
A        int16   Q2.13    9 coefficients
acc_i    int32            sum_k A[i][k] * I'_k
g_i      int18   Q2.13    clamp((acc_i + 128) >> 8, -32768, 32767)
rho2     uint32           sum_i g_i^2
rho      uint16  Q2.13    isqrt(rho2)
inv      uint16  Q2.13    32768 if rho < 2048 else min(32768, 2^26 // rho)
n_i      int18   Q1.13    (g_i * inv) >> 13
normal8                   clamp(((n_i + 8192) * 255 + 8192) >> 14, 0, 255)
albedo8                   clamp((rho * 255 + 4096) >> 13, 0, 255)
rel_q13  int              (sum_i g_i * lv_i + 8192) >> 14
relight8                  clamp((rel_q13 * 255 + 4096) >> 13, 0, 255)
conf8                     0 if min(I) <= low or max(I) >= sat or rho < mag else 255
"""
import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def isqrt_u32(x):
    r = np.sqrt(x.astype(np.float64)).astype(np.int64)
    r = np.where((r + 1) * (r + 1) <= x, r + 1, r)
    r = np.where(r * r > x, r - 1, r)
    return r


def load_frame(path):
    with open(path) as f:
        vals = [int(line.strip(), 16) for line in f if line.strip()]
    v = np.array(vals, dtype=np.int64)
    return ((v >> 16) & 0xFF), ((v >> 8) & 0xFF), (v & 0xFF)


def run(img, meta):
    r, g, b = img
    I = np.stack([r, g, b], axis=-1).astype(np.int64)          # (N, 3) uint8

    wb = np.array(meta["wb_q8"], dtype=np.int64)
    Ip = np.minimum((I * wb[None, :]) >> 8, 1023)               # uint10

    A = np.array(meta["a_q13"], dtype=np.int64)                 # 3x3 int16
    acc = Ip @ A.T                                              # int32
    gvec = np.clip((acc + 128) >> 8, -32768, 32767)             # int18 Q2.13

    rho2 = np.sum(gvec * gvec, axis=1)                          # uint32
    rho = isqrt_u32(rho2)                                       # uint16 Q2.13

    small = rho < 2048
    inv = np.full_like(rho, 32768)
    ok = ~small
    inv[ok] = np.minimum(32768, (1 << 26) // np.maximum(rho[ok], 1))

    n = (gvec * inv[:, None]) >> 13                             # int18 Q1.13
    normal8 = np.clip(((n + 8192) * 255 + 8192) >> 14, 0, 255).astype(np.uint8)
    albedo8 = np.clip((rho * 255 + 4096) >> 13, 0, 255).astype(np.uint8)

    relights = []
    for lv in meta["light_q14"]:
        lv = np.array(lv, dtype=np.int64)
        rq = (np.sum(gvec * lv[None, :], axis=1) + 8192) >> 14
        relights.append(np.clip((rq * 255 + 4096) >> 13, 0, 255).astype(np.uint8))

    th = meta["thresh"]
    conf = np.full(I.shape[0], 255, dtype=np.uint8)
    bad = (I.min(axis=1) <= th["low"]) | (I.max(axis=1) >= th["sat"]) | (rho < th["mag"])
    conf[bad] = 0

    return normal8, albedo8, relights, conf, rho, n


def write_hex(path, arr, nibbles):
    with open(path, "w") as f:
        if nibbles == 6:
            f.write("\n".join(f"{a:02x}{b:02x}{c:02x}" for a, b, c in arr))
        else:
            f.write("\n".join(f"{v:02x}" for v in arr))
        f.write("\n")


def write_ppm(path, w, h, rgb):
    with open(path, "wb") as f:
        f.write(f"P6\n{w} {h}\n255\n".encode())
        f.write(np.asarray(rgb, dtype=np.uint8).tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stem", default="golden")
    ap.add_argument("--frame", default=os.path.join("stim", "frame.hex"))
    ap.add_argument("--meta", default=os.path.join("stim", "meta.json"))
    ap.add_argument("--gt", default=os.path.join("stim", "gt_normal.npy"))
    args = ap.parse_args()

    stim = os.path.join(ROOT, "stim")
    out = os.path.join(ROOT, "out")
    os.makedirs(out, exist_ok=True)

    with open(os.path.join(ROOT, args.meta)) as f:
        meta = json.load(f)
    w, h = meta["width"], meta["height"]
    img = load_frame(os.path.join(ROOT, args.frame))

    normal8, albedo8, relights, conf, rho, n = run(img, meta)

    write_hex(os.path.join(out, f"{args.stem}_normal.hex"), normal8, 6)
    write_hex(os.path.join(out, f"{args.stem}_albedo.hex"), albedo8, 2)
    write_hex(os.path.join(out, f"{args.stem}_relight0.hex"), relights[0], 2)
    write_hex(os.path.join(out, f"{args.stem}_relight1.hex"), relights[1], 2)
    write_hex(os.path.join(out, f"{args.stem}_conf.hex"), conf, 2)

    write_ppm(os.path.join(out, f"{args.stem}_normal.ppm"), w, h, normal8)
    write_ppm(os.path.join(out, f"{args.stem}_albedo.ppm"), w, h,
              np.stack([albedo8] * 3, axis=-1))
    write_ppm(os.path.join(out, f"{args.stem}_relight0.ppm"), w, h,
              np.stack([relights[0]] * 3, axis=-1))

    # error against the ground truth normals (float), for the record
    try:
        gt = np.load(os.path.join(ROOT, args.gt)).reshape(-1, 3)
        if not np.any(gt):
            raise FileNotFoundError
        nf = n.astype(np.float64) / 8192.0
        nf /= np.maximum(np.linalg.norm(nf, axis=1, keepdims=True), 1e-9)
        good = (rho >= 2048) & (conf == 255)
        ang = np.degrees(np.arccos(np.clip(np.sum(nf * gt, axis=1), -1, 1)))
        print(f"pixels      : {normal8.shape[0]}")
        print(f"conf==0     : {int((conf == 0).sum())} ({(conf == 0).mean() * 100:.1f}%)")
        if good.any():
            print(f"angle error : mean {ang[good].mean():.3f} deg  "
                  f"p95 {np.percentile(ang[good], 95):.3f} deg")
        else:
            print("angle error : no confident pixels in this frame")
    except FileNotFoundError:
        pass

    print(f"wrote {out}/{args.stem}_*.hex")


if __name__ == "__main__":
    sys.exit(main())
