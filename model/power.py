#!/usr/bin/env python3
"""Switching power from a real simulation waveform plus the extracted parasitics.

    python3 model/power.py --spef runs/.../chromaps.nom.spef --vcd out/power.vcd

Reads the SPEF that OpenROAD wrote (per-net capacitance) and the VCD that the
gate-level bench dumped, counts 0->1 transitions per net in the steady-state
window, and reports

    P_sw = sum_net C_net * V^2 * f_01

which is the textbook switching term with measured activity and extracted
capacitance, not a default toggle rate.
"""
import argparse
import re
from collections import defaultdict


def parse_spef(path):
    """name -> capacitance in pF, using the file's name map."""
    names = {}
    caps = {}
    in_map = False
    with open(path) as f:
        for line in f:
            if line.startswith("*NAME_MAP"):
                in_map = True
                continue
            if line.startswith("*D_NET"):
                in_map = False
                parts = line.split()
                caps[parts[1]] = float(parts[2])
                continue
            if in_map:
                m = re.match(r"\*(\d+)\s+(\S+)", line)
                if m:
                    names["*" + m.group(1)] = m.group(2)
                else:
                    in_map = False
    return {names.get(k, k): v for k, v in caps.items()}, names


def parse_vcd(path):
    """Returns (id -> (name, width), id -> transition count in window)."""
    info = {}
    changes = defaultdict(int)
    prev = {}
    t = 0
    t0 = t1 = None
    window = (1_000_000, 5_000_000)      # ps: after reset, before drain
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line[0] == "#":
                t = int(line[1:])
                continue
            if line.startswith("$var"):
                p = line.split()
                width = int(p[2])
                ident = p[3]
                name = p[4]
                info[ident] = (name, width)
                continue
            if line[0] in "01xzXZ" and " " not in line:
                val, ident = line[0], line[1:]
            elif line[0] in "bB":
                parts = line.split()
                if len(parts) < 2:
                    continue
                val, ident = parts[0], parts[1]
            else:
                continue
            old = prev.get(ident)
            prev[ident] = val
            if t0 is None and t >= window[0]:
                t0 = t
            if t0 is not None and t <= window[1] and old is not None and old != val:
                changes[ident] += 1
                if t1 is None or t > t1:
                    t1 = t
    return info, changes, (window[0], window[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spef", required=True)
    ap.add_argument("--vcd", required=True)
    ap.add_argument("--voltage", type=float, default=1.8)
    ap.add_argument("--default-switching", type=float, default=0.241,
                    help="OpenSTA default-activity switching power, for reference")
    args = ap.parse_args()

    caps, _ = parse_spef(args.spef)
    info, changes, (ta, tb) = parse_vcd(args.vcd)
    T = (tb - ta) * 1e-12

    total = 0.0
    matched = 0
    net_energy = []
    for ident, (name, width) in info.items():
        c = caps.get(name)
        if c is None:
            continue
        matched += 1
        n = changes.get(ident, 0)
        if n == 0:
            continue
        # a vector change is treated as one bit toggling on average (pessimistic
        # for buses, which are a tiny fraction of the nets here)
        f01 = (n / 2.0) / T
        p = c * 1e-12 * args.voltage ** 2 * f01
        total += p
        net_energy.append((p, name, n))

    net_energy.sort(reverse=True)
    edges = sum(changes.values())
    cycles = T / 25e-9
    per_net = edges / cycles / len(info) if info else 0.0
    print(f"nets matched    : {matched} / {len(caps)}")
    print(f"window          : {T*1e9:.0f} ns = {cycles:.0f} cycles")
    print(f"transitions     : {edges} total, {edges/cycles:.0f} per cycle")
    print(f"activity        : {per_net:.3f} transitions per net per cycle "
          f"(tool default: 0.100)")
    print(f"wire-only power : {total*1e3:.1f} mW  <-- lower bound; the SPEF holds "
          f"wire capacitance only")
    print(f"tool default    : {args.default_switching:.3f} W switching at 0.1 activity")
    print("\ntop nets:")
    for p, name, n in net_energy[:8]:
        print(f"  {p*1e3:7.3f} mW  {n:6d} edges  {name}")


if __name__ == "__main__":
    main()
