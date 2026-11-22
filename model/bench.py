#!/usr/bin/env python3
"""Throughput comparison for the same per-pixel arithmetic.

Measures what we can measure on this machine (numpy, scalar Python) and prints
the published chip number next to it.  The Cortex-M4 column is an estimate from
a cycle budget, not a measurement - it is labelled as such.
"""
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
import golden  # noqa: E402

W, H = 640, 480
N = W * H


def make_frame():
    rng = np.random.default_rng(1)
    return (rng.integers(90, 210, (N, 3))).T


def meta():
    L = np.array([[0.5, 0.0, 0.866025],
                  [-0.25, 0.433013, 0.866025],
                  [-0.25, -0.433013, 0.866025]])
    A = np.linalg.inv(L)
    q13 = lambda x: int(round(x * 8192))
    q14 = lambda x: int(round(x * 16384))
    return {
        "a_q13": [[q13(v) for v in row] for row in A],
        "wb_q8": [256, 256, 256],
        "light_q14": [[q14(v) for v in v_] for v_ in
                      ([0.492, -0.587, 0.643], [0.262, 0.719, 0.643])],
        "thresh": {"low": 4, "sat": 251, "mag": 2048},
    }


def bench_numpy(img, m, reps=10):
    golden.run(img, m)
    t = time.perf_counter()
    for _ in range(reps):
        golden.run(img, m)
    return (time.perf_counter() - t) / reps


def bench_scalar(img, m, n=3000):
    A = np.array(m["a_q13"], dtype=np.int64)
    flat = np.stack(img, axis=-1).reshape(-1, 3)[:n]
    t = time.perf_counter()
    for px in flat:
        x0, x1, x2 = (px * 256) >> 8
        a0 = A[0, 0] * x0 + A[0, 1] * x1 + A[0, 2] * x2
        a1 = A[1, 0] * x0 + A[1, 1] * x1 + A[1, 2] * x2
        a2 = A[2, 0] * x0 + A[2, 1] * x1 + A[2, 2] * x2
        g0 = max(-32768, min(32767, (a0 + 128) >> 8))
        g1 = max(-32768, min(32767, (a1 + 128) >> 8))
        g2 = max(-32768, min(32767, (a2 + 128) >> 8))
        rho = int((g0 * g0 + g1 * g1 + g2 * g2) ** 0.5)
        inv = 32768 if rho < 2048 else min(32768, (1 << 26) // rho)
        n0 = (g0 * inv) >> 13
        n1 = (g1 * inv) >> 13
        n2 = (g2 * inv) >> 13
        _ = ((n0 + 8192) * 255 + 8192) >> 14, ((n1 + 8192) * 255 + 8192) >> 14, \
            ((n2 + 8192) * 255 + 8192) >> 14
    return (time.perf_counter() - t) / len(flat)


def main():
    img = make_frame()
    m = meta()

    t_np = bench_numpy(img, m)
    t_py = bench_scalar(img, m)

    np_mpx = N / t_np / 1e6
    py_mpx = 1 / t_py / 1e6

    # Cortex-M4 cycle budget: nine MAC, three squares, a 16-iteration integer
    # square root, one 32/32 divide, three normal multiplies, six relight MACs,
    # encoding and loop overhead.
    mcu_cycles = 250
    mcu_mhz = 168
    mcu_mpx = mcu_mhz * 1e6 / mcu_cycles / 1e6

    print(f"frame            : {W}x{H} = {N} pixels")
    print(f"numpy            : {t_np*1e3:7.2f} ms/frame   {np_mpx:8.2f} Mpixel/s")
    print(f"scalar Python    : {t_py*1e6:7.2f} us/pixel    {py_mpx:8.3f} Mpixel/s")
    print()
    print("throughput, pixels per second (higher is better)")
    rows = [
        ("ChromaPS @ 40 MHz signoff", 40.0, "measured in RTL"),
        ("ChromaPS @ ~85 MHz (TT corner)", 85.0, "measured in RTL"),
        ("numpy on this laptop", np_mpx, "measured"),
        ("Cortex-M4 @ 168 MHz", mcu_mpx, f"estimated, {mcu_cycles} cycles/px"),
        ("scalar Python", py_mpx, "measured"),
    ]
    for name, v, note in rows:
        bar = "#" * max(1, int(round(40 * (v / 85))))
        print(f"  {name:32s} {v:8.2f} Mpx/s  {bar:40s} {note}")
    print()
    print(f"640x480 @ 30 fps needs 9.2 Mpixel/s; 320x240 @ 30 fps needs 2.3 Mpixel/s.")


if __name__ == "__main__":
    main()
