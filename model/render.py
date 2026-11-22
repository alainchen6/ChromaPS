#!/usr/bin/env python3
"""Generate the input frame and ground truth for one test case.

Renders a synthetic single-shot photometric-stereo capture: one 8-bit RGB
image of a scene lit by three directional R/G/B lights, plus the ground-truth
normals and the configuration words the RTL needs.

Outputs (under --out-dir):
    frame.hex      one pixel per line, rrggbb
    frame.ppm      same image, for eyeballing
    gt_normal.npy  ground-truth normals, float32 (H, W, 3)
    meta.json      matrix A, white balance, virtual lights, thresholds
    cfg.hex        32 configuration words, one 8-digit hex per line
"""
import argparse
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def q13(x):
    return int(round(float(x) * 8192.0))


def q14(x):
    return int(round(float(x) * 16384.0))


def camera(eye, target, up, fov_deg, w, h):
    eye = np.asarray(eye, float)
    fwd = np.asarray(target, float) - eye
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, np.asarray(up, float))
    right /= np.linalg.norm(right)
    upv = np.cross(right, fwd)
    j, i = np.mgrid[0:h, 0:w]
    px = (i + 0.5) / w * 2 - 1
    py = 1 - (j + 0.5) / h * 2
    tanf = np.tan(np.deg2rad(fov_deg) / 2)
    d = (fwd[None, None, :]
         + right[None, None, :] * (px[..., None] * tanf * (w / h))
         + upv[None, None, :] * (py[..., None] * tanf))
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    return eye, d, (fwd, right, upv)


def camera_rig(basis, theta_deg, az_deg):
    """Three lights evenly spaced around the camera axis (a ring around the lens)."""
    fwd, right, upv = basis
    t = np.deg2rad(theta_deg)
    L = []
    for a in np.deg2rad(az_deg):
        v = np.cos(t) * (-fwd) + np.sin(t) * (np.cos(a) * right + np.sin(a) * upv)
        L.append(v / np.linalg.norm(v))
    return np.stack(L)


def world_rig(theta_deg, az_deg):
    t = np.deg2rad(theta_deg)
    return np.stack([[np.sin(t) * np.cos(np.deg2rad(a)),
                      np.sin(t) * np.sin(np.deg2rad(a)),
                      np.cos(t)] for a in az_deg])


# ------------------------------------------------------------------ scenes
def height_plate(x, y):
    r2 = x * x + y * y
    dome = 0.50 * np.exp(-r2 / 0.40)
    ripple = 0.06 * np.sin(5.0 * x + 1.3) * np.sin(5.0 * y)
    ridge = 0.07 * np.exp(-((y - 0.90) ** 2) / 0.05) * np.exp(-(x ** 2) / 3.0)
    return dome + ripple + ridge


def height_bumps(x, y):
    return (0.060 * np.sin(8.0 * x + 0.4) * np.sin(8.0 * y)
            + 0.040 * np.cos(13.0 * x) * np.cos(11.0 * y + 1.7)
            + 0.060 * np.exp(-(((x - 0.55) ** 2 + (y + 0.35) ** 2) / 0.22)))


def render_heightfield(hfun, w, h, eye, target, fov, cell=2.4, lo=0.36, hi=0.90):
    e, d, basis = camera(eye, target, [0, 0, 1], fov, w, h)
    t = (0.0 - e[2]) / d[..., 2]
    for _ in range(2):
        p = e + d * t[..., None]
        t = (hfun(p[..., 0], p[..., 1]) - e[2]) / d[..., 2]
    p = e + d * t[..., None]
    x, y = p[..., 0], p[..., 1]
    eps = 1e-4
    hx = (hfun(x + eps, y) - hfun(x - eps, y)) / (2 * eps)
    hy = (hfun(x, y + eps) - hfun(x, y - eps)) / (2 * eps)
    n = np.stack([-hx, -hy, np.ones_like(hx)], axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    if cell > 0:
        chk = ((np.floor(cell * x) + np.floor(cell * y)) % 2)
        albedo = lo + (hi - lo) * chk
    else:
        albedo = np.full_like(x, lo)
    return n, albedo, np.ones_like(x, dtype=bool), basis


def scene_plate(w, h):
    return render_heightfield(height_plate, w, h, [0.0, -3.1, 2.5], [0.0, 0.25, 0.05], 36)


def scene_bumps(w, h):
    return render_heightfield(height_bumps, w, h, [0.0, -2.3, 2.3], [0.0, 0.0, 0.0], 40,
                              cell=0.0, lo=0.80, hi=0.80)


def scene_sphere(w, h):
    e, d, basis = camera([0.0, -4.0, 1.1], [0.0, 0.0, 0.0], [0, 0, 1], 34, w, h)
    c, r = np.array([0.0, 0.0, 0.0]), 1.0
    tp = np.full(d.shape[:-1], np.inf)
    oc = e - c
    b = 2 * np.dot(d, oc)
    cc = np.dot(oc, oc) - r * r
    disc = b * b - 4 * cc
    ts = (-b - np.sqrt(np.maximum(disc, 0))) / 2
    hit = (disc > 0) & (ts > 1e-4)
    t = np.where(hit, ts, tp)
    p = e + d * t[..., None]
    n = np.where(hit[..., None], (p - c) / r, np.array([0.0, 0.0, 1.0]))
    albedo = np.where(hit, 0.90, 0.0)
    return n, albedo, hit, basis


SCENES = {"plate": scene_plate, "sphere": scene_sphere, "bumps": scene_bumps,
          "noise": scene_plate, "dark": scene_plate}


# ------------------------------------------------------------------ output
def write_cfg(path, meta):
    a = meta["a_q13"]
    words = [1]
    for row in a:
        words += row
    words += meta["wb_q8"]
    for lv in meta["light_q14"]:
        words += lv
    th = meta["thresh"]
    words.append((th["mag"] << 16) | (th["sat"] << 8) | th["low"])
    words += [0] * (31 - len(words))
    words.append(0x00010000)
    with open(path, "w") as f:
        f.write("\n".join(f"{w & 0xFFFFFFFF:08x}" for w in words))
        f.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="plate", choices=sorted(SCENES))
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--height", type=int, default=240)
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "stim"))
    ap.add_argument("--rig", default="world", choices=["world", "camera"])
    ap.add_argument("--elevation", type=float, default=30.0)
    ap.add_argument("--relight-az", type=float, nargs=2, default=[-50.0, 70.0])
    ap.add_argument("--exposure", type=float, default=1.0)
    ap.add_argument("--noise", type=float, default=0.0, help="gaussian sigma, 8-bit counts")
    ap.add_argument("--specular", type=float, default=0.0, help="specular weight, 0 = pure Lambertian")
    ap.add_argument("--shininess", type=float, default=24.0)
    ap.add_argument("--vignette", type=float, default=0.0, help="0..1, lens falloff")
    ap.add_argument("--texture", type=float, default=0.0, help="albedo grain, 0..1")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    w, h = args.width, args.height
    n, albedo, mask, basis = SCENES[args.scene](w, h)

    if args.texture > 0:
        rng = np.random.default_rng(4)
        albedo = np.clip(albedo * (1.0 + args.texture * rng.normal(0, 0.09, albedo.shape)), 0, 1)

    if args.rig == "camera":
        L = camera_rig(basis, args.elevation, (0.0, 120.0, 240.0))
    else:
        L = world_rig(args.elevation, (0.0, 120.0, 240.0))
    A = np.linalg.inv(L)
    ndotl = np.einsum("...k,jk->...j", n, L)
    img = np.clip(ndotl, 0, None) * albedo[..., None] * args.exposure

    if args.specular > 0:
        fwd = basis[0]
        for k in range(3):
            hv = L[k] + fwd
            hv = hv / np.linalg.norm(hv)
            spec = np.clip(np.einsum("...k,k->...", n, hv), 0, None) ** args.shininess
            img[..., k] += args.specular * spec * args.exposure

    if args.vignette > 0:
        yy, xx = np.mgrid[0:h, 0:w]
        rr = ((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2
        img *= (1.0 - 0.34 * args.vignette * np.clip(rr, 0, 1))[..., None]

    if args.noise > 0:
        rng = np.random.default_rng(args.seed)
        img = img + rng.normal(0.0, args.noise, img.shape) / 255.0

    # 8-bit capture, no ambient term (the model assumes pure Lambertian)
    img8 = np.clip(np.round(img * 255.0), 0, 255).astype(np.uint8)

    out = args.out_dir
    os.makedirs(out, exist_ok=True)

    flat = img8.reshape(-1, 3)
    with open(os.path.join(out, "frame.hex"), "w") as f:
        f.write("\n".join(f"{r:02x}{g:02x}{b:02x}" for r, g, b in flat))
        f.write("\n")

    with open(os.path.join(out, "frame.ppm"), "wb") as f:
        f.write(f"P6\n{w} {h}\n255\n".encode())
        f.write(img8.tobytes())

    np.save(os.path.join(out, "gt_normal.npy"), n.astype(np.float32))
    np.save(os.path.join(out, "mask.npy"), mask)

    meta = {
        "scene": args.scene,
        "rig": args.rig,
        "width": w,
        "height": h,
        "exposure": args.exposure,
        "noise": args.noise,
        "specular": args.specular,
        "vignette": args.vignette,
        "texture": args.texture,
        "a_q13": [[q13(v) for v in row] for row in A],
        "wb_q8": [256, 256, 256],
        "light_q14": [[q14(v) for v in world_rig(40.0, (az,))[0]]
                      for az in args.relight_az],
        "thresh": {"low": 4, "sat": 251, "mag": 2048},
        "lights_q13": [[q13(v) for v in row] for row in L],
    }
    with open(os.path.join(out, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    write_cfg(os.path.join(out, "cfg.hex"), meta)

    print(f"{args.scene}: {w}x{h} -> {out}  ({flat.shape[0]} pixels)")


if __name__ == "__main__":
    main()
