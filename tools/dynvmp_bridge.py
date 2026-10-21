#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function

import argparse
import json
import os
import sys
import traceback

from alib import datamodel
from vnep_approx.treewidth_model import DynVMPAlgorithm, TreeDecomposition, compute_tree_decomposition

TYPE_NAME = "t1"


def _load_json(path):
    with open(path, 'r') as f:
        return json.load(f)


def _dump_json(path, obj):
    with open(path, 'w') as f:
        json.dump(obj, f, indent=2, sort_keys=True)


def _soft_substrate_caps(payload):
    """Return very large substrate capacities so DynVMP treats valid mappings as
    topology/qualification constrained, not per-request capacity constrained.

    This matches the simulator and the original reference implementation, where
    r(A) and xi(e) are used for queue/resource accounting and routing costs, but
    do not make a mapping infeasible merely because a single physical edge has a
    smaller instantaneous service rate than the dependency scaling factor.
    """
    total_node_demand = 0.0
    for item in payload["dag"]["functions"]:
        total_node_demand += float(item.get("r", 0.0))
    total_edge_demand = 0.0
    for edge in payload["dag"].get("edges", []):
        total_edge_demand += float(edge.get("xi", 0.0))
    for item in payload["dag"].get("sources", []):
        total_edge_demand += float(item.get("xi", 0.0))
    for item in payload["dag"].get("sinks", []):
        total_edge_demand += float(item.get("xi", 0.0))

    # Add a margin and keep the number finite for the legacy Py2 code path.
    node_cap = max(1.0, total_node_demand + 1.0)
    edge_cap = max(1.0, total_edge_demand + 1.0)
    return node_cap, edge_cap


def _build_substrate(payload):
    sub = datamodel.Substrate("substrate")
    soft_node_cap, soft_edge_cap = _soft_substrate_caps(payload)
    for node in payload["network"]["nodes"]:
        u = str(node["id"])
        q = float(node.get("queue_cost", 0.0))
        # NOTE: use soft capacities instead of the physical service rates; the
        # latter are enforced by the simulator queues, not by valid-mapping
        # feasibility inside DynVMP.
        sub.add_node(u, types=[TYPE_NAME], capacity={TYPE_NAME: soft_node_cap}, cost={TYPE_NAME: q})
    for edge in payload["network"]["edges"]:
        u = str(edge["tail"])
        v = str(edge["head"])
        q = float(edge.get("queue_cost", 0.0))
        sub.add_edge(u, v, capacity=soft_edge_cap, cost=q, bidirected=False)
    return sub


def _build_request(payload):
    req = datamodel.Request(str(payload.get("commodity_name", "commodity")))

    for item in payload["dag"]["functions"]:
        i = str(item["id"])
        r = float(item.get("r", 0.0))
        allowed_nodes = [str(u) for u in item.get("allowed_nodes", [])]
        req.add_node(i, r, TYPE_NAME, allowed_nodes=allowed_nodes)

    for item in payload["dag"].get("sources", []):
        func = str(item["function"])
        src_node = str(item["physical_node"])
        aux = "SRC__{}".format(func)
        req.add_node(aux, 0.0, TYPE_NAME, allowed_nodes=[src_node])
        req.add_edge(aux, func, float(item["xi"]))

    for item in payload["dag"].get("sinks", []):
        func = str(item["function"])
        dst_node = str(item["physical_node"])
        aux = "SNK__{}".format(func)
        req.add_node(aux, 0.0, TYPE_NAME, allowed_nodes=[dst_node])
        req.add_edge(func, aux, float(item["xi"]))

    for edge in payload["dag"]["edges"]:
        req.add_edge(str(edge["tail"]), str(edge["head"]), float(edge["xi"]))

    return req


def _request_undirected_adjacency(req):
    adj = {}
    for node in req.nodes:
        adj[node] = set()
    for (u, v) in req.edges:
        adj[u].add(v)
        adj[v].add(u)
    return adj


def _min_fill_score(adj, node):
    nbrs = list(adj[node])
    missing = 0
    i = 0
    while i < len(nbrs):
        j = i + 1
        while j < len(nbrs):
            if nbrs[j] not in adj[nbrs[i]]:
                missing += 1
            j += 1
        i += 1
    return (missing, len(nbrs), str(node))


def _min_fill_order(adj):
    work = {}
    for node, nbrs in adj.iteritems():
        work[node] = set(nbrs)
    order = []
    while work:
        node = min(work.keys(), key=lambda x: _min_fill_score(work, x))
        nbrs = set(work[node])
        order.append(node)
        nbr_list = list(nbrs)
        i = 0
        while i < len(nbr_list):
            a = nbr_list[i]
            j = i + 1
            while j < len(nbr_list):
                b = nbr_list[j]
                work[a].add(b)
                work[b].add(a)
                j += 1
            i += 1
        for other in nbrs:
            work[other].discard(node)
        del work[node]
    return order


def _td_from_elimination_order(graph_name, adj, order):
    work = {}
    for node, nbrs in adj.iteritems():
        work[node] = set(nbrs)

    bag_specs = []
    for node in order:
        nbrs = set(work[node])
        bag = frozenset([node] + list(nbrs))
        bag_specs.append((node, bag))
        nbr_list = list(nbrs)
        i = 0
        while i < len(nbr_list):
            a = nbr_list[i]
            j = i + 1
            while j < len(nbr_list):
                b = nbr_list[j]
                work[a].add(b)
                work[b].add(a)
                j += 1
            i += 1
        for other in nbrs:
            work[other].discard(node)
        del work[node]

    td = TreeDecomposition("{}_TD_HEUR".format(graph_name))
    node_to_bagid = {}
    pos = {}
    for idx, (node, bag) in enumerate(bag_specs):
        bag_id = "bag_{}".format(idx)
        td.add_node(bag_id, node_bag=bag)
        node_to_bagid[node] = bag_id
        pos[node] = idx

    roots = []
    for node, bag in bag_specs:
        later_nodes = [other for other in (bag - frozenset([node])) if pos[other] > pos[node]]
        if later_nodes:
            parent = min(later_nodes, key=lambda x: pos[x])
            td.add_edge(node_to_bagid[node], node_to_bagid[parent])
        else:
            roots.append(node)

    if len(roots) > 1:
        prev = roots[0]
        for node in roots[1:]:
            td.add_edge(node_to_bagid[prev], node_to_bagid[node])
            prev = node

    return td


def _heuristic_tree_decomposition(req):
    adj = _request_undirected_adjacency(req)
    order = _min_fill_order(adj)
    td = _td_from_elimination_order(req.name, adj, order)
    if not td.nodes:
        raise ValueError("Heuristic tree decomposition construction produced no bags")
    if not td.is_tree_decomposition(req):
        raise ValueError("Heuristic tree decomposition is invalid for request {}".format(req.name))
    return td


def _compute_td(req):
    mode = os.environ.get("DCNC_TD_MODE", "heuristic").strip().lower()
    if mode not in ("heuristic", "auto", "pace", "pace-strict"):
        mode = "heuristic"

    pace_exc = None
    if mode in ("auto", "pace", "pace-strict"):
        try:
            td = compute_tree_decomposition(req)
            if td is None or not getattr(td, 'nodes', None):
                raise ValueError("PACE returned an empty tree decomposition")
            if not td.is_tree_decomposition(req):
                raise ValueError("PACE returned an invalid tree decomposition")
            return td, "pace"
        except Exception as exc:
            pace_exc = exc
            if mode == "pace-strict":
                raise
            if mode == "pace":
                raise

    td = _heuristic_tree_decomposition(req)
    if pace_exc is None:
        return td, "heuristic"
    return td, "heuristic_fallback_after_pace_failure: {}".format(repr(pace_exc))


def _mapping_to_output(payload, mapping, td_meta):
    function_ids = [str(item["id"]) for item in payload["dag"]["functions"]]
    out = {
        "status": "ok",
        "assign": {},
        "paths": [],
        "objective": 0.0,
        "td_method": td_meta.get("td_method"),
        "td_width": td_meta.get("td_width"),
        "td_bags": td_meta.get("td_bags"),
        "capacity_mode": "topology_only_soft_caps",
    }

    for f_id in function_ids:
        out["assign"][f_id] = str(mapping.mapping_nodes[f_id])

    total_cost = 0.0
    edge_cost_lookup = {}
    for e in payload["network"]["edges"]:
        edge_cost_lookup[(str(e["tail"]), str(e["head"]))] = float(e.get("queue_cost", 0.0))
    node_cost_lookup = {}
    for n in payload["network"]["nodes"]:
        node_cost_lookup[str(n["id"])] = float(n.get("queue_cost", 0.0))

    function_r = {str(item["id"]): float(item.get("r", 0.0)) for item in payload["dag"]["functions"]}
    for f_id, u in out["assign"].iteritems():
        total_cost += function_r[f_id] * node_cost_lookup.get(str(u), 0.0)

    for edge in payload["dag"]["edges"]:
        tail = str(edge["tail"])
        head = str(edge["head"])
        xi = float(edge["xi"])
        path = mapping.mapping_edges[(tail, head)]
        out["paths"].append({
            "kind": "internal",
            "tail": tail,
            "head": head,
            "path": [[str(u), str(v)] for (u, v) in path],
        })
        total_cost += xi * sum(edge_cost_lookup.get((str(u), str(v)), 0.0) for (u, v) in path)

    for item in payload["dag"].get("sources", []):
        func = str(item["function"])
        xi = float(item["xi"])
        aux = "SRC__{}".format(func)
        path = mapping.mapping_edges[(aux, func)]
        out["paths"].append({
            "kind": "source",
            "function": func,
            "path": [[str(u), str(v)] for (u, v) in path],
        })
        total_cost += xi * sum(edge_cost_lookup.get((str(u), str(v)), 0.0) for (u, v) in path)

    for item in payload["dag"].get("sinks", []):
        func = str(item["function"])
        xi = float(item["xi"])
        aux = "SNK__{}".format(func)
        path = mapping.mapping_edges[(func, aux)]
        out["paths"].append({
            "kind": "sink",
            "function": func,
            "path": [[str(u), str(v)] for (u, v) in path],
        })
        total_cost += xi * sum(edge_cost_lookup.get((str(u), str(v)), 0.0) for (u, v) in path)

    out["objective"] = total_cost
    return out


def main():
    ap = argparse.ArgumentParser(description="Run DynVMP on a JSON payload and write a JSON mapping result.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    try:
        payload = _load_json(args.input)
        sub = _build_substrate(payload)
        req = _build_request(payload)

        algo = DynVMPAlgorithm(req, sub)
        sub.initialize_shortest_paths_costs()
        td, td_method = _compute_td(req)
        if td is None or not td.nodes:
            raise ValueError("No valid tree decomposition was produced for request {}".format(req.name))
        algo.tree_decomposition = td
        algo.tree_decomposition_arb = td.convert_to_arborescence()
        mapping = algo.compute_valid_mapping()
        if mapping is None:
            _dump_json(args.output, {
                "status": "error",
                "message": "DynVMP found no feasible mapping",
                "td_method": td_method,
                "td_width": td.width,
                "td_bags": len(td.nodes),
            })
            return 2
        _dump_json(args.output, _mapping_to_output(payload, mapping, {
            "td_method": td_method,
            "td_width": td.width,
            "td_bags": len(td.nodes),
        }))
        return 0
    except Exception as exc:
        err = {
            "status": "error",
            "message": repr(exc),
            "traceback": traceback.format_exc(),
        }
        try:
            _dump_json(args.output, err)
        except Exception:
            pass
        sys.stderr.write(err["traceback"] + "\n")
        sys.stderr.flush()
        return 1


if __name__ == '__main__':
    sys.exit(main())
