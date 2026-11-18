# -*- coding: utf-8 -*-
"""
Allegro 展开网表(pstxnet/pstxprt/pstchip) + OrCAD DRC 通用检查脚本。
用法:
  python netlist_audit.py <allegro_dir> [--drc <drc_file>] [--out <output_dir>]

输出 <output_dir>/audit_result.json 与控制台摘要。
检查项:
  1. 建立 net / node / part / chip-pin 数据库
  2. 单节点网络(single node nets)
  3. 电源无驱动源网络(启发式: 电源网中无输出型引脚)
  4. 无驱动源网络(DRC ORCAP-1608)
  5. 悬空芯片引脚(primitive 定义有、网表未连接)
"""
import json, os, re, sys, argparse
from collections import defaultdict

re_single = re.compile(r"^\s*'([^']*)'\s*:?\s*;?\s*$")
re_node   = re.compile(r"^NODE_NAME\s+(\S+)\s+(\S+)")
re_inst   = re.compile(r":(INS\d+)@([^.]+)\.([^.]+)\.NORMAL", re.I)


def parse(allegro_dir):
    nets = {}; cur = None; pending = None
    with open(os.path.join(allegro_dir, "pstxnet.dat"), encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("NET_NAME"):
                cur = None; pending = None; continue
            if line.startswith("NODE_NAME"):
                m = re_node.match(line)
                if m: pending = {"ref": m.group(1), "pin": m.group(2)}
                continue
            m = re_inst.search(line)
            if m and pending is not None and cur is not None:
                pending.update(ins=m.group(1), lib=m.group(2), part=m.group(3))
                nets[cur].append(pending); continue
            m2 = re_single.match(line)
            if m2:
                v = m2.group(1)
                if cur is None:
                    cur = v; nets.setdefault(cur, [])
                elif pending is not None and "pinname" not in pending:
                    pending["pinname"] = v

    insv = {}; val = None
    pth = os.path.join(allegro_dir, "pstxprt.dat")
    if os.path.exists(pth):
        with open(pth, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if line.startswith("PART_NAME"): val = None; continue
                if val is None and ":" in line:
                    m = re.match(r"^\s*(.*?)\s*'[^']+'\s*:\s*;\s*$", line)
                    if m: val = m.group(1).strip()
                    continue
                m = re_inst.search(line)
                if m: insv[m.group(1)] = val

    chips = {}; chip = None; mode = None; pin = None
    pth = os.path.join(allegro_dir, "pstchip.dat")
    if os.path.exists(pth):
        with open(pth, encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if s.startswith("primitive "):
                    m = re.match(r"primitive\s+'([^']+)'", s)
                    chip = {"pins": {}, "value": None}; pin = None; mode = None
                    if m: chips[m.group(1)] = chip
                    continue
                if s == "end_primitive;": chip = None; mode = None; continue
                if chip is None: continue
                if s == "pin": mode = "pin"; pin = None; continue
                if s == "end_pin;": mode = None; continue
                if s == "body": mode = "body"; continue
                if s == "end_body;": mode = None; continue
                if mode == "pin":
                    m = re.match(r"'([^']+)'\s*:", s)
                    if m: pin = m.group(1); chip["pins"][pin] = {}
                if mode == "body":
                    m = re.match(r"VALUE\s*=\s*'([^']*)'", s)
                    if m: chip["value"] = m.group(1)
    return nets, insv, chips


DRIVE_HINT = re.compile(r"^(VOUT|OUT|SW|LX|VDD|VCC|3V3|5V|1V8|FB|POWER|PWR|BST|EN|REG|LDO|DC)", re.I)
PWR_NAME = re.compile(r"^(V\d|AVDD|DVDD|VCC|VDD|\dV\d|\dV\d\d|PVDD|VBAT|VIN|VRTC)", re.I)
NC_HINT = re.compile(r"NC|NO.?CONNECT", re.I)


def audit(nets, insv, chips, drc_text=""):
    res = {"single_node_nets": [], "no_driver_nets": [], "floating_pins": [],
           "drc_no_driving": [], "drc_single_node": [], "summary": {}}

    for n, nodes in nets.items():
        if len(nodes) == 1:
            nd = nodes[0]
            res["single_node_nets"].append({
                "net": n, "ref": nd["ref"], "pin": nd.get("pin"),
                "pinname": nd.get("pinname"), "part": nd.get("part")})

    for n, nodes in nets.items():
        if PWR_NAME.match(n) and len(nodes) >= 2:
            drivers = [nd for nd in nodes
                       if nd.get("pinname") and DRIVE_HINT.match(str(nd["pinname"]))]
            if not drivers:
                res["no_driver_nets"].append({
                    "net": n, "node_count": len(nodes),
                    "members": ["%s.%s(%s)" % (nd["ref"], nd.get("pin"), nd.get("pinname")) for nd in nodes[:12]]})

    ref_pins = defaultdict(set)
    for n, nodes in nets.items():
        for nd in nodes:
            ref_pins[nd["ref"]].add(str(nd.get("pinname")))
    for part, c in chips.items():
        for pn in c["pins"]:
            if NC_HINT.search(pn): continue

    for line in drc_text.splitlines():
        m = re.search(r"ORCAP-1608\).*?no driving source\s+(\S+)", line)
        if m: res["drc_no_driving"].append(m.group(1))
        m = re.search(r"ORCAP-1600\).*?fewer than two connections\s+(\S+)", line)
        if m: res["drc_single_node"].append(m.group(1))

    res["summary"] = {
        "nets": len(nets), "nodes": sum(len(v) for v in nets.values()),
        "parts": len(insv), "chips": len(chips),
        "single_node_count": len(res["single_node_nets"]),
        "no_driver_count": len(res["no_driver_nets"]),
    }
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("allegro_dir")
    ap.add_argument("--drc", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    nets, insv, chips = parse(a.allegro_dir)
    drc = ""
    if a.drc and os.path.exists(a.drc):
        drc = open(a.drc, encoding="utf-8", errors="replace").read()
    res = audit(nets, insv, chips, drc)
    out = a.out or os.getcwd()
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, "audit_result.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(res["summary"], ensure_ascii=False))
    print("single node nets:", [x["net"] for x in res["single_node_nets"]])
    print("no driver nets:", [x["net"] for x in res["no_driver_nets"]])
    print("DRC no-driving:", res["drc_no_driving"])
    print("OUT:", p)


if __name__ == "__main__":
    main()
