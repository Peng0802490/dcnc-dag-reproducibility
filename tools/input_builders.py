"""Deterministic input reconstruction from public structures and explicit recipes."""
from collections import deque
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import re

ROOT = Path(__file__).resolve().parents[1]
CONSTRUCTION = ROOT / "inputs/construction"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def verify_sources():
    for source in read_json(CONSTRUCTION / "sources.json")["files"]:
        path = ROOT / source["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("Construction source checksum mismatch: " + source["path"])


def generate_roofnet(recipe):
    """Rebuild coordinates/links; capacity and access dynamics are separate overlays."""
    rng = random.Random(recipe["coordinate_seed"])
    positions = [(rng.uniform(0, recipe["side_km"]), rng.uniform(0, recipe["side_km"]))
                 for _ in range(recipe["node_count"])]
    net = copy.deepcopy(recipe["header"])
    net["network_id"] = "Roofnet-38-emulated"
    net["metadata"].pop("capacity_model", None)
    net["metadata"].pop("dynamic_model", None)
    net["nodes"] = [dict(id=f"N{i+1}", role="COMPUTE", capacity=1.0,
                         x_km=round(x, 4), y_km=round(y, 4))
                    for i, (x, y) in enumerate(positions)]
    net["edges"] = []
    for i, (x, y) in enumerate(positions):
        for j in range(i + 1, len(positions)):
            distance = math.hypot(x - positions[j][0], y - positions[j][1])
            if distance <= recipe["radius_km"]:
                for u, v in ((i, j), (j, i)):
                    net["edges"].append(dict(
                        **{"from": f"N{u+1}", "to": f"N{v+1}"},
                        capacity=1.0, dynamic=False, distance_km=round(distance, 4), emulated=True))
    return net


def apply_capacities(network, seed):
    """Same ordered randint sequence as the historical rescale_networks.py."""
    network = copy.deepcopy(network)
    rng = random.Random(seed)
    for node in network["nodes"]:
        node["capacity"] = rng.randint(2, 10)
    for edge in network["edges"]:
        edge["capacity"] = rng.randint(2, 10)
    network["network_id"] += "-cap210"
    network.setdefault("metadata", {})["capacity_model"] = (
        f"node and directed-arc capacities i.i.d. uniform on {{2,...,10}}, seed {seed}")
    return network


def apply_access_dynamics(network, config, p_on=0.8):
    """Same endpoint rule as the historical make_access_dynamic.py."""
    if not 0 <= p_on <= 1:
        raise ValueError("p_on must be in [0,1]")
    network = copy.deepcopy(network)
    endpoints = set()
    for commodity in config["service_dags"]:
        endpoints.update(map(str, commodity.get("sources", {}).values()))
        endpoints.update(map(str, commodity.get("sinks", {}).values()))
    known = {node["id"] for node in network["nodes"]}
    if not endpoints <= known:
        raise ValueError("An endpoint is absent from the network")
    for edge in network["edges"]:
        edge["dynamic"] = edge["from"] in endpoints or edge["to"] in endpoints
        if edge["dynamic"]:
            edge["p_on"] = p_on
        else:
            edge.pop("p_on", None)
    network["network_id"] += "-access"
    network.setdefault("metadata", {})["dynamic_model"] = (
        f"only arcs incident to source/sink endpoints are dynamic (p_on={p_on})")
    return network


def public_workflow_structure(name, recipe, node_parameters):
    path = CONSTRUCTION / recipe["source"]
    if name == "srasearch22":
        tasks = read_json(path)["workflow"]["specification"]["tasks"]
        mapping = {row["source_task"]: row["service_task"] for row in node_parameters}
        source_ids = {task["id"] for task in tasks}
        if source_ids != set(mapping):
            raise ValueError("SRA public task set disagrees with the explicit task map")
        edges = {(mapping[task["id"]], mapping[child])
                 for task in tasks for child in task["children"]}
        parents = {(mapping[parent], mapping[task["id"]])
                   for task in tasks for parent in task["parents"]}
        if edges != parents:
            raise ValueError("Public SRA parent/child declarations disagree")
        return set(mapping.values()), edges
    if name == "sipht31":
        text = path.read_text(encoding="utf-8")
        nodes = set(re.findall(r'"([^"]+_ID\d+)"\s*\[', text))
        edges = set(re.findall(r'"([^"]+)"\s*->\s*"([^"]+)"', text))
        # Exclude Pegasus create-directory and stage-out infrastructure jobs.
        edges = {(u, v) for u, v in edges if u in nodes and v in nodes}
        if nodes != {row["source_task"] for row in node_parameters}:
            raise ValueError("SIPHT public task set disagrees with the explicit task map")
        return nodes, edges
    raise ValueError("Unknown workflow: " + name)


def validate_dag(nodes, edges):
    indegree = {node: 0 for node in nodes}
    successors = {node: [] for node in nodes}
    for u, v in edges:
        if u not in nodes or v not in nodes:
            raise ValueError("Dependency references an unknown node")
        indegree[v] += 1
        successors[u].append(v)
    ready = deque(node for node in nodes if indegree[node] == 0)
    count = 0
    while ready:
        u = ready.popleft()
        count += 1
        for v in successors[u]:
            indegree[v] -= 1
            if indegree[v] == 0:
                ready.append(v)
    if count != len(nodes):
        raise ValueError("Workflow contains a cycle")


def convert_workflow(name, public_only=False):
    recipe = read_json(CONSTRUCTION / "workflow_recipes.json")[name]
    node_parameters = [r for r in read_csv(CONSTRUCTION / "workflow_node_parameters.csv") if r["workflow"] == name]
    edge_parameters = [r for r in read_csv(CONSTRUCTION / "workflow_edge_parameters.csv") if r["workflow"] == name]
    nodes, edges = public_workflow_structure(name, recipe, node_parameters)
    validate_dag(nodes, edges)
    if public_only:
        return dict(nodes=sorted(nodes), edges=[list(e) for e in sorted(edges)])
    remove = set(map(tuple, recipe["edge_adaptations"]["remove"]))
    add = set(map(tuple, recipe["edge_adaptations"]["add"]))
    if not remove <= edges or add & edges:
        raise ValueError("Declared adaptations disagree with the public dependency graph")
    edges = (edges - remove) | add
    parameter_edges = [(r["source"], r["target"]) for r in edge_parameters]
    if set(parameter_edges) != edges or len(parameter_edges) != len(edges):
        raise ValueError("Dependency parameter table disagrees with the adapted structure")
    if len(node_parameters) != len(nodes):
        raise ValueError("Duplicate node parameter")
    validate_dag(nodes, edges)
    dag = copy.deepcopy(recipe["header"])
    dag["nodes"], dag["edges"] = [], []
    for row in node_parameters:
        node_id = row["service_task"]
        actual_type = ("source" if not any(v == node_id for u, v in edges) else
                       "sink" if not any(u == node_id for u, v in edges) else "function")
        if row["type"] != actual_type:
            raise ValueError("Node type disagrees with dependency structure")
        node = dict(id=node_id, type=row["type"], r=float(row["r"]))
        for field, column in [("in", "input_workload"), ("out", "output_workload")]:
            if row[column] != "":
                node[field] = float(row[column])
        dag["nodes"].append(node)
    for row in edge_parameters:
        dag["edges"].append({"from": row["source"], "to": row["target"], "xi": float(row["xi"])})
    return dag
