#!/usr/bin/env python3
"""RoofNet/FlockLab variants where only the access arcs carry wireless dynamics.

Both dense topologies currently flag every arc as dynamic.  Combined with
primary interference on a near-complete graph (FlockLab: 338 arcs over 26
nodes), a multi-hop route loses 20% of its arcs every slot, which is why the
Randomized baseline never reaches a 0.95 completion ratio there even at an
offered rate of 0.0006.  Restricting the dynamics to the arcs incident to the
source and sink endpoints matches what Milan and the random topology already do
and makes the four subfigures use one wireless model instead of two.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "legacy_inputs"


def variant(cfg_name, net_out, cfg_out):
    cfg = json.loads((ROOT / cfg_name).read_text(encoding="utf-8"))
    net = json.loads((ROOT / cfg["network"]["file"]).read_text(encoding="utf-8"))
    endpoints = set()
    for s in cfg["service_dags"]:
        endpoints.update(str(v) for v in s.get("sources", {}).values())
        endpoints.update(str(v) for v in s.get("sinks", {}).values())
    n = 0
    for e in net["edges"]:
        dyn = str(e["from"]) in endpoints or str(e["to"]) in endpoints
        e["dynamic"] = dyn
        if dyn:
            e["p_on"] = 0.8
            n += 1
        else:
            e.pop("p_on", None)
    net["network_id"] = str(net.get("network_id", "")) + "-access"
    net.setdefault("metadata", {})["dynamic_model"] = (
        "only arcs incident to source/sink endpoints are dynamic (p_on=0.8)")
    (ROOT / "Network" / net_out).write_text(json.dumps(net, indent=2), encoding="utf-8")
    cfg["network"]["file"] = "Network/" + net_out
    (ROOT / cfg_out).write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print("%-42s endpoints=%-22s dynamic_arcs=%d/%d" %
          (cfg_out, sorted(endpoints), n, len(net["edges"])))


variant("config_random6_FlockLab_cap210.json", "FlockLab_cap210_access.json",
        "config_random6_FlockLab_cap210_access.json")
variant("config_random6_Roofnet38_cap210.json", "Roofnet38_cap210_access.json",
        "config_random6_Roofnet38_cap210_access.json")
