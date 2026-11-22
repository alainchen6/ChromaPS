#!/usr/bin/env python3
"""Run every test case end to end and produce a report.

For each case:
  1. render  -- model/render.py writes stimulus, ground truth and cfg.hex
  2. golden  -- model/golden.py computes the expected outputs (independent
                fixed-point implementation, not derived from the RTL)
  3. rtl     -- Icarus Verilog runs the RTL on the same stimulus
  4. compare -- byte-for-byte diff of the five output channels
  5. score   -- angular error against the ray-traced normals, which is a
                third, independent reference (neither model nor RTL)

Nothing here reads an RTL output to build an expectation.
"""
import json
import os
import shutil
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IV = shutil.which("iverilog") or "iverilog"
VVP = shutil.which("vvp") or "vvp"
PY = sys.executable

SRC = ["src/chromaps.sv", "src/mat3.sv", "src/isqrt16.sv", "src/recip.sv"]
TB = "tb/tb_rtl.sv"

# name, scene, width, height, render options
CASES = [
    ("plate",  "plate",  320, 240, {}),
    ("sphere", "sphere", 320, 240, {"rig": "camera"}),
    ("bumps",  "bumps",  320, 240, {}),
    ("tilted", "plate",  320, 240, {"elevation": 22.0}),  # different A: tests cfg loading
    ("noise",  "plate",  320, 240, {"noise": 6.0}),
    ("dark",   "plate",  320, 240, {"exposure": 0.30}),
    ("studio", "plate",  320, 240, {"specular": 0.18, "shininess": 26.0, "vignette": 0.55, "noise": 1.5, "texture": 0.6}),
    ("edge",   "edge",     8,   4, None),   # directed cases, see model/edge.py
]


def run(cmd, **kw):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        print(p.stdout)
        print(p.stderr)
        raise SystemExit(f"command failed: {' '.join(cmd)}")
    return p.stdout


def load_hex(path, nibbles):
    with open(path) as f:
        return np.array([int(line.strip(), 16) for line in f if line.strip()], dtype=np.int64)


def encode(n):
    return np.clip(np.round((n * 0.5 + 0.5) * 255), 0, 255).astype(np.uint8)


def angular_error(normal24, gt):
    """normal24: HxW packed RGB; gt: HxWx3 ground truth. Returns degrees."""
    r = (normal24 >> 16) & 0xFF
    g = (normal24 >> 8) & 0xFF
    b = normal24 & 0xFF
    n = np.stack([r, g, b], -1).astype(np.float64) / 255.0 * 2.0 - 1.0
    n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-9)
    c = np.clip(np.sum(n * gt, axis=-1), -1, 1)
    return np.degrees(np.arccos(c))


def build(width, height):
    vvp = os.path.join(ROOT, "build", f"tb_{width}x{height}.vvp")
    os.makedirs(os.path.dirname(vvp), exist_ok=True)
    if not os.path.exists(vvp):
        run([IV, "-g2012", f"-Ptb_rtl.W={width}", f"-Ptb_rtl.H={height}",
             "-o", vvp, TB] + SRC)
    return vvp


def run_case(name, scene, width, height, opts):
    stim = os.path.join("stim", name)
    os.makedirs(os.path.join(ROOT, stim), exist_ok=True)

    if opts is None:
        run([PY, "model/edge.py"])
        with open(os.path.join(ROOT, stim, "meta.json")) as f:
            meta = json.load(f)
    else:
        cmd = [PY, "model/render.py", "--scene", scene,
               "--width", str(width), "--height", str(height), "--out-dir", stim]
        for k, v in opts.items():
            cmd += [f"--{k}", str(v)]
        run(cmd)
        with open(os.path.join(ROOT, stim, "meta.json")) as f:
            meta = json.load(f)

    run([PY, "model/golden.py",
         "--frame", os.path.join(stim, "frame.hex"),
         "--meta", os.path.join(stim, "meta.json"),
         "--gt", os.path.join(stim, "gt_normal.npy"),
         "--stem", f"{name}_golden"])

    vvp = build(width, height)
    run([VVP, vvp,
         f"+stim={stim}/frame.hex", f"+cfg={stim}/cfg.hex", f"+prefix=out/{name}"])

    out = os.path.join(ROOT, "out")
    chans = [("normal", 6), ("albedo", 2), ("relight0", 2), ("relight1", 2), ("conf", 2)]
    bad = 0
    for ch, _ in chans:
        a = load_hex(os.path.join(out, f"{name}_golden_{ch}.hex"), 0)
        b = load_hex(os.path.join(out, f"{name}_{ch}.hex"), 0)
        if a.shape != b.shape:
            raise SystemExit(f"{name}/{ch}: length mismatch {a.shape} vs {b.shape}")
        bad += int((a != b).sum())

    normal = load_hex(os.path.join(out, f"{name}_normal.hex"), 0).reshape(height, width)
    conf = load_hex(os.path.join(out, f"{name}_conf.hex"), 0).reshape(height, width)
    gt = np.load(os.path.join(stim, "gt_normal.npy")).reshape(height, width, 3)

    ang = angular_error(normal, gt)
    mask_path = os.path.join(stim, "mask.npy")
    mask = np.load(mask_path) if os.path.exists(mask_path) else np.ones((height, width), bool)
    good = (conf == 255) & mask
    # where the ground truth is all-zero (edge case has no real geometry) the
    # angle is meaningless, so only score scenes that produce a normal field
    if not np.any(gt):
        good[:] = False

    res = {
        "name": name,
        "size": f"{width}x{height}",
        "pixels": int(width * height),
        "mismatch": bad,
        "confident_pct": round(100.0 * good.sum() / max(int(mask.sum()), 1), 2),
        "angle_mean": round(float(ang[good].mean()), 3) if good.any() else None,
        "angle_p95": round(float(np.percentile(ang[good], 95)), 3) if good.any() else None,
        "angle_max_conf": round(float(ang[good].max()), 2) if good.any() else None,
        "over10deg_confident": int(((ang > 10) & good).sum()),
        "meta": meta.get("scene", name),
    }
    return res


def main():
    results = []
    for name, scene, w, h, opts in CASES:
        print(f"== {name} ({w}x{h})")
        res = run_case(name, scene, w, h, opts)
        results.append(res)
        print(f"   mismatch={res['mismatch']}  confident={res['confident_pct']}%  "
              f"mean={res['angle_mean']}  p95={res['angle_p95']}")

    out = os.path.join(ROOT, "out")
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(results, f, indent=2)

    lines = ["| case | size | pixels | RTL vs model | confident | mean err | p95 | >10° |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        status = "bit-exact" if r["mismatch"] == 0 else f"{r['mismatch']} diffs"
        mean = "-" if r["angle_mean"] is None else f"{r['angle_mean']:.2f}°"
        p95 = "-" if r["angle_p95"] is None else f"{r['angle_p95']:.2f}°"
        lines.append(f"| {r['name']} | {r['size']} | {r['pixels']} | {status} | "
                     f"{r['confident_pct']}% | {mean} | {p95} | {r['over10deg_confident']} |")
    table = "\n".join(lines)
    with open(os.path.join(out, "report.md"), "w") as f:
        f.write("# ChromaPS test report\n\n" + table + "\n")

    print()
    print(table)

    fails = [r for r in results if r["mismatch"] != 0]
    if fails:
        print(f"\nFAIL: {len(fails)} case(s) differ from the model")
        return 1
    print("\nPASS: all cases bit-exact against the model")
    return 0


if __name__ == "__main__":
    sys.exit(main())
