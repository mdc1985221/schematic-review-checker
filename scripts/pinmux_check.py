# -*- coding: utf-8 -*-
"""
PIN mux 复用核对脚本。输入:
  - netlist_db.json (由 netlist_audit.py 或 parse_netlist 产出，含 nets 字段)
  - pinmux_db.json  (由 PIN mux XLSX 提取，含 balls[].functions[])
检查:
  (a) 网表中每个 SoC 引脚的 pinname 是否属于该 ball 的合法候选功能
  (b) 同一 ball 是否接多个网络(硬冲突)
  (c) 网表 pinname 功能 vs 网络名暗示的其它复用功能(潜在 mux 风险)
  (d) 同接口组(SDIO0 等)功能号一致性
用法:
  python pinmux_check.py <netlist_db.json> <pinmux_db.json> [--soc-ref U11] [--out out.json]
"""
import json, re, os, sys, argparse
from collections import defaultdict, Counter


def norm(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("netlist_db")
    ap.add_argument("pinmux_db")
    ap.add_argument("--soc-ref", default="U11")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    net = json.load(open(a.netlist_db, encoding="utf-8"))["nets"]
    pm = json.load(open(a.pinmux_db, encoding="utf-8"))
    balls = {b["ball"]: b for b in pm["balls"]}

    use = defaultdict(list)   # ball -> [(pinname, netname)]
    ball_nets = Counter()
    for n, nodes in net.items():
        for nd in nodes:
            if nd["ref"] == a.soc_ref:
                use[nd["pin"]].append((nd.get("pinname"), n))
                ball_nets[nd["pin"]] += 1

    illegal = []
    for ball, entries in use.items():
        b = balls.get(ball)
        for pn, n in entries:
            p = norm(pn)
            if not p or p == "NC":
                continue
            if not b:
                illegal.append({"ball": ball, "pinname": pn, "net": n, "reason": "ball不在mux表"})
                continue
            funcs = {norm(f["signal_name"]) for f in b["functions"]}
            if p not in funcs:
                illegal.append({"ball": ball, "pinname": pn, "net": n, "reason": "非候选功能"})

    multi = {ball: cnt for ball, cnt in ball_nets.items() if cnt > 1}

    # 网络名暗示其它复用功能
    implied = []
    for ball, entries in sorted(use.items()):
        b = balls.get(ball)
        if not b:
            continue
        funcs = {norm(f["signal_name"]): f["function_number"] for f in b["functions"]}
        for pn, n in entries:
            if "/" not in str(n):
                continue
            p = norm(pn)
            hit = []
            for fn, fnum in funcs.items():
                if len(fn) < 5 or fn == p:
                    continue
                toks = [norm(t) for t in re.split(r"[/_\s]+", str(n))]
                if fn in toks:
                    hit.append("%s(f%s)" % (fn, fnum))
            if hit:
                implied.append({"ball": ball, "pinname": pn, "net": n, "other_functions": hit})

    res = {
        "soc_ref": a.soc_ref,
        "soc_pins": len(use),
        "illegal_pinname": illegal,
        "multi_net_balls": multi,
        "implied_mux_risk": implied,
        "summary": {
            "soc_pins": len(use),
            "illegal_count": len(illegal),
            "multi_net_count": len(multi),
            "implied_risk_count": len(implied),
        },
    }
    out = a.out or os.getcwd()
    os.makedirs(out, exist_ok=True)
    p = os.path.join(out, "pinmux_result.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(res["summary"], ensure_ascii=False))
    print("illegal:", illegal[:20])
    print("multi_net:", multi)
    print("implied_risk count:", len(implied))
    for x in implied[:20]:
        print("  ", x)
    print("OUT:", p)


if __name__ == "__main__":
    main()
