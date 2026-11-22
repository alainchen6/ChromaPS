#!/usr/bin/env python3
"""Transparent overlay layers for the interactive die figure.

Every layer is a full die-sized RGBA image, so the page can stack them over the
GDS render and fade them in and out independently.

  cells    -> one rectangle per standard cell, coloured by class
  clock    -> the clock nets' routed metal
  routing  -> wire length per 8 um bin
  power    -> switching power per 8 um bin, from VCD activity x SPEF capacitance

    python3 model/die_layers.py --run runs/pnr --vcd out/power.vcd --out docs/img/die
"""
import argparse
import json
import os
import re
from collections import defaultdict

import numpy as np
from PIL import Image

W_UM, H_UM = 1127.44, 1138.16
SCALE = 1.0                      # output pixels per micron
BIN_UM = 14.0                    # heatmap bin size
VOLT = 1.8

BG = (19, 17, 16)

CLASS_COLORS = {
    "logic":   (44, 99, 92, 105),
    "seq":     (201, 119, 77, 205),
    "clock":   (242, 201, 160, 220),
    "antenna": (224, 90, 74, 255),
}
CLOCK_COLOR = (143, 240, 224, 215)


def parse_def(path):
    """components, per-net routed segments, and special-net segments."""
    comps = []
    nets = defaultdict(list)
    special = defaultdict(list)
    section = None
    net = None
    in_special = False
    cre = re.compile(r"^\s*-\s+(\S+)\s+(\S+)\s+.*?PLACED\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)")
    netre = re.compile(r"^\s*-\s+(\S+)")
    segpat = re.compile(r"^\s*(?:\+ ROUTED|NEW)\s+(\w+)(.*)")
    pt = re.compile(r"\(\s*(\*|-?\d+)\s+(\*|-?\d+)\s*\)")

    with open(path, errors="ignore") as f:
        for line in f:
            st = line.strip()
            if st.startswith("COMPONENTS"):
                section = "comp"
                continue
            if st.startswith("END COMPONENTS"):
                section = None
                continue
            if st.startswith("SPECIALNETS"):
                in_special, section = True, "nets"
                continue
            if st.startswith("END SPECIALNETS"):
                in_special, section = False, None
                continue
            if st.startswith("NETS"):
                section = "nets"
                continue
            if st.startswith("END NETS"):
                section = None
                continue
            if section == "comp":
                m = cre.match(line)
                if m:
                    comps.append((m.group(2), int(m.group(3)) / 1000.0, int(m.group(4)) / 1000.0))
            elif section == "nets":
                if st.startswith("- "):
                    net = st.split()[1]
                    continue
                if not net:
                    continue
                m = segpat.match(line)
                if not m:
                    continue
                pts, px, py = [], None, None
                for a, b in pt.findall(m.group(2)):
                    if (a == "*" and px is None) or (b == "*" and py is None):
                        continue
                    x = px if a == "*" else int(a) / 1000.0
                    y = py if b == "*" else int(b) / 1000.0
                    px, py = x, y
                    pts.append((x, y))
                target = special if in_special else nets
                for p0, p1 in zip(pts, pts[1:]):
                    target[net].append((p0[0], p0[1], p1[0], p1[1]))
    return comps, nets, special


def lef_sizes(path):
    sizes, name = {}, None
    with open(path, errors="ignore") as f:
        for line in f:
            s = line.strip()
            if s.startswith("MACRO "):
                name = s.split()[1]
            elif s.startswith("SIZE ") and name:
                m = re.match(r"SIZE ([\d.]+) BY ([\d.]+)", s)
                if m:
                    sizes[name] = (float(m.group(1)), float(m.group(2)))
            elif s == "END":
                name = None
    return sizes


def spef_caps(path):
    names, caps, in_map = {}, {}, False
    with open(path, errors="ignore") as f:
        for line in f:
            if line.startswith("*NAME_MAP"):
                in_map = True
                continue
            if line.startswith("*D_NET"):
                in_map = False
                p = line.split()
                caps[p[1]] = float(p[2])
                continue
            if in_map:
                m = re.match(r"\*(\d+)\s+(\S+)", line)
                if m:
                    names["*" + m.group(1)] = m.group(2)
                else:
                    in_map = False
    return {names.get(k, k): v for k, v in caps.items()}


def vcd_activity(path, t0=1_000_000, t1=9_000_000):
    info, changes, prev = {}, defaultdict(int), {}
    t = 0
    with open(path, errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line[0] == "#":
                t = int(line[1:])
                continue
            if line.startswith("$var"):
                p = line.split()
                info[p[3]] = p[4]
                continue
            if line[0] in "01xzXZ" and " " not in line:
                val, ident = line[0], line[1:]
            elif line[0] in "bB":
                p = line.split()
                if len(p) < 2:
                    continue
                val, ident = p[0], p[1]
            else:
                continue
            old = prev.get(ident)
            prev[ident] = val
            if old is not None and old != val and t0 <= t <= t1:
                changes[ident] += 1
    return {info[k]: v for k, v in changes.items() if k in info}, (t1 - t0) * 1e-12


def smooth(a, passes=2):
    for _ in range(passes):
        b = a.copy()
        b[1:-1, 1:-1] = (a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:] + 4 * a[1:-1, 1:-1]) / 8.0
        a = b
    return a


def heat(bins, rgb_lo, rgb_hi, alpha_max):
    bins = smooth(bins.astype(np.float64), 2)
    nb = bins.shape[0]
    v = bins / max(np.percentile(bins[bins > 0], 99) if np.any(bins > 0) else 1, 1e-9)
    v = np.clip(v, 0, 1) ** 0.72
    lo = np.array(rgb_lo, np.float32)
    hi = np.array(rgb_hi, np.float32)
    img = (lo[None, None, :] + (hi - lo)[None, None, :] * v[..., None]).astype(np.uint8)
    a = (v * alpha_max).astype(np.uint8)
    rgba = np.dstack([img, a])
    return np.array(Image.fromarray(rgba, "RGBA").resize(
        (int(W_UM * SCALE), int(H_UM * SCALE)), Image.BILINEAR))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--vcd", required=True)
    ap.add_argument("--pdk", default=os.path.expanduser(
        "~/.ciel/ciel/sky130/versions/0fe599b2afb6708d281543108caf8310912f54af/sky130A"))
    ap.add_argument("--out", default=os.path.join("docs", "img", "die"))
    args = ap.parse_args()
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.out)
    os.makedirs(out, exist_ok=True)

    comps, nets, special = parse_def(os.path.join(args.run, "final/def/chromaps.def"))
    sizes = lef_sizes(os.path.join(args.pdk, "libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"))
    caps = spef_caps(os.path.join(args.run, "final/spef/nom/chromaps.nom.spef"))
    act, window = vcd_activity(args.vcd)
    print(f"components {len(comps)}, nets {len(nets)}, caps {len(caps)}, active {len(act)}")

    ox, oy = 0.0, 0.0
    cw, ch = int(W_UM * SCALE), int(H_UM * SCALE)

    # ---- cells
    cells = np.zeros((ch, cw, 4), np.uint8)
    for master, x, y in comps:
        if master.startswith("sky130_fd_sc_hd__fill") or master.startswith("sky130_fd_sc_hd__decap") \
                or master.startswith("sky130_fd_sc_hd__tap"):
            continue
        if master.startswith("sky130_fd_sc_hd__diode"):
            c = CLASS_COLORS["antenna"]
        elif re.match(r"sky130_fd_sc_hd__(clkbuf|clkinv)", master):
            c = CLASS_COLORS["clock"]
        elif re.match(r"sky130_fd_sc_hd__(df|dl|sdf)", master):
            c = CLASS_COLORS["seq"]
        else:
            c = CLASS_COLORS["logic"]
        w, h = sizes.get(master, (1.0, 2.7))
        x0, y0 = int(x * SCALE), int((H_UM - y - h) * SCALE)
        x1, y1 = min(cw, int((x + w) * SCALE)), min(ch, int((H_UM - y) * SCALE))
        if x1 > x0 and y1 > y0:
            cells[max(0, y0):y1, max(0, x0):x1] = c
    Image.fromarray(cells, "RGBA").save(os.path.join(out, "cells.png"), optimize=True)
    print("cells.png")

    # ---- clock + routing bins
    nb = int(np.ceil(max(W_UM, H_UM) / BIN_UM))
    route_bins = np.zeros((nb, nb), np.float64)
    clock = np.zeros((ch, cw, 4), np.uint8)
    for name, segs in nets.items():
        is_clk = "clk" in name
        for x0, y0, x1, y1 in segs:
            L = abs(x1 - x0) + abs(y1 - y0)
            route_bins[int((x0 + x1) / 2 / BIN_UM), int((y0 + y1) / 2 / BIN_UM)] += L
            if is_clk:
                X0, Y0 = int(min(x0, x1)), int(ch - max(y0, y1))
                X1, Y1 = int(max(x0, x1)) + 1, int(ch - min(y0, y1)) + 1
                clock[max(0, Y0):min(ch, Y1), max(0, X0):min(cw, X1)] = CLOCK_COLOR
    Image.fromarray(clock, "RGBA").save(os.path.join(out, "clock.png"), optimize=True)
    print("clock.png")

    # ---- routing heat
    rt = np.zeros((nb, nb, 4), np.uint8)
    Image.fromarray(heat(route_bins, (30, 120, 110), (243, 205, 166), 150), "RGBA").save(
        os.path.join(out, "routing.png"), optimize=True)
    print("routing.png")

    # ---- power: activity x capacitance, spread along each net's wire
    p_bins = np.zeros((nb, nb), np.float64)
    used = 0
    for name, segs in nets.items():
        c = caps.get(name)
        n = act.get(name)
        if not c or not n:
            continue
        f01 = (n / 2.0) / window
        p = c * 1e-12 * VOLT ** 2 * f01
        total_len = sum(abs(x1 - x0) + abs(y1 - y0) for x0, y0, x1, y1 in segs)
        if total_len <= 0:
            continue
        used += 1
        for x0, y0, x1, y1 in segs:
            L = abs(x1 - x0) + abs(y1 - y0)
            p_bins[int((x0 + x1) / 2 / BIN_UM), int((y0 + y1) / 2 / BIN_UM)] += p * L / total_len
    print(f"power: {used} nets with both activity and capacitance")
    Image.fromarray(heat(p_bins, (60, 20, 15), (255, 210, 150), 185), "RGBA").save(
        os.path.join(out, "power.png"), optimize=True)
    print("power.png", "max bin", float(p_bins.max()))

    # ---- power grid (PDN): special nets
    pdn = np.zeros((ch, cw, 4), np.uint8)
    for name, segs in special.items():
        for x0, y0, x1, y1 in segs:
            X0, X1 = int(min(x0, x1)), int(max(x0, x1)) + 1
            Y0, Y1 = int(ch - max(y0, y1)), int(ch - min(y0, y1)) + 1
            pdn[max(0, Y0):min(ch, Y1), max(0, X0):min(cw, X1)] = (243, 205, 166, 190)
    Image.fromarray(pdn, "RGBA").save(os.path.join(out, "pdn.png"), optimize=True)
    print("pdn.png")

    # ---- placement density (cell area per bin)
    area_bins = np.zeros((nb, nb), np.float64)
    cell_count = np.zeros((nb, nb), np.float64)
    for master, x, y in comps:
        w, h = sizes.get(master, (1.0, 2.7))
        i = min(nb - 1, int(x / BIN_UM))
        j = min(nb - 1, int(y / BIN_UM))
        area_bins[i, j] += w * h
        cell_count[i, j] += 1
    Image.fromarray(heat(area_bins, (26, 70, 66), (210, 240, 225), 165), "RGBA").save(
        os.path.join(out, "placement.png"), optimize=True)
    print("placement.png")

    # ---- dots: antenna diodes and clock buffers
    def dots(pred, color, r=1):
        img = np.zeros((ch, cw, 4), np.uint8)
        n = 0
        for master, x, y in comps:
            if not pred(master):
                continue
            n += 1
            X, Y = int(x * SCALE), int((H_UM - y) * SCALE)
            img[max(0, Y - r):min(ch, Y + r + 1), max(0, X - r):min(cw, X + r + 1)] = color
        return img, n

    img, nd = dots(lambda m: m.startswith("sky130_fd_sc_hd__diode"), (240, 96, 72, 255), 2)
    Image.fromarray(img, "RGBA").save(os.path.join(out, "diodes.png"), optimize=True)
    print("diodes.png", nd)

    img, nc = dots(lambda m: bool(re.match(r"sky130_fd_sc_hd__(clkbuf|clkinv)", m)), (250, 214, 170, 235), 1)
    Image.fromarray(img, "RGBA").save(os.path.join(out, "clockcells.png"), optimize=True)
    print("clockcells.png", nc)

    # ---- probe grids for the hover read-out (14 um bins, upscaled in the page)
    probe = {
        "w": int(nb), "h": int(nb), "bin_um": BIN_UM,
        "power": [round(float(v) * 1e9, 1) for v in p_bins.T.ravel()],      # nW
        "routing": [round(float(v), 0) for v in route_bins.T.ravel()],      # um
        "cells": [int(v) for v in cell_count.T.ravel()],
    }
    with open(os.path.join(out, "probe.js"), "w") as f:
        f.write("window.DIE_PROBE=" + json.dumps(probe, separators=(",", ":")) + ";\n")
    print("probe.js", round(os.path.getsize(os.path.join(out, "probe.js")) / 1e3), "KB")

    # ---- metadata for the page
    meta = {
        "power_nets": used,
        "window_ns": round(window * 1e9, 1),
        "max_bin_uW": round(float(p_bins.max()) * 1e6, 3),
        "clock_nets": sum(1 for n in nets if "clk" in n),
        "routing_um": round(float(route_bins.sum()), 0),
    }
    with open(os.path.join(out, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(meta)


if __name__ == "__main__":
    main()
