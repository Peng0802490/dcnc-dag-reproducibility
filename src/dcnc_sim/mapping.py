from __future__ import annotations

import itertools
import json
import logging
import math
import os
import random
import shlex
import subprocess
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from .models import Commodity, DistributedComputingNetwork, Edge, NodeId, ServiceDAG

PseudoNode = Tuple[str, str]
MappingEdgeKey = Tuple[Any, Any]

# Tie-break for the exact mapper: when several valid mappings attain the same
# queue-weighted minimum (common on dense, lightly loaded topologies where most
# link queues are zero), prefer the one traversing fewest links.  Matches the
# epsilon already used by BaseMappingSolver._edge_cost_fn for greedy/CTS.
_TIEBREAK_EPS = 1e-9


@dataclass
class ValidMapping:
    assign: Dict[NodeId, NodeId]
    edge_paths: Dict[MappingEdgeKey, List[Edge]] = field(default_factory=dict)
    total_cost: float = math.inf

    def set_edge_path(self, edge_key: MappingEdgeKey, path_edges: Sequence[Edge]) -> None:
        self.edge_paths[edge_key] = list(path_edges)

    def path_for(self, edge_key: MappingEdgeKey) -> List[Edge]:
        return list(self.edge_paths.get(edge_key, []))


class DijkstraOracle:
    def __init__(self, network: DistributedComputingNetwork):
        self.network = network

    def shortest_path(
        self,
        src: NodeId,
        dst: NodeId,
        edge_cost: Callable[[NodeId, NodeId], float],
    ) -> Tuple[float, List[Edge]]:
        src = str(src)
        dst = str(dst)
        if src == dst:
            return 0.0, []
        dist: Dict[NodeId, float] = defaultdict(lambda: math.inf)
        prev: Dict[NodeId, NodeId] = {}
        visited: set[NodeId] = set()
        import heapq

        dist[src] = 0.0
        pq: List[Tuple[float, NodeId]] = [(0.0, src)]
        while pq:
            cur_d, u = heapq.heappop(pq)
            if u in visited:
                continue
            visited.add(u)
            if u == dst:
                break
            for v in self.network.delta_plus(u):
                c = float(edge_cost(u, v))
                nd = cur_d + c
                if nd < dist[v]:
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))
        if math.isinf(dist[dst]):
            return math.inf, []
        path_nodes = [dst]
        cur = dst
        while cur != src:
            cur = prev[cur]
            path_nodes.append(cur)
        path_nodes.reverse()
        path_edges = [(path_nodes[i], path_nodes[i + 1]) for i in range(len(path_nodes) - 1)]
        return dist[dst], path_edges

    def all_simple_paths(self, src: NodeId, dst: NodeId, cutoff: Optional[int] = None) -> List[List[Edge]]:
        src = str(src)
        dst = str(dst)
        if src == dst:
            return [[]]
        cutoff = cutoff if cutoff is not None else len(self.network.nodes_all()) - 1
        results: List[List[Edge]] = []
        stack: List[Tuple[NodeId, Iterator[NodeId]]] = [(src, iter(self.network.delta_plus(src)))]
        path_nodes: List[NodeId] = [src]
        visited = {src}
        while stack:
            parent, children = stack[-1]
            try:
                child = next(children)
            except StopIteration:
                stack.pop()
                visited.discard(path_nodes.pop())
                continue
            if child in visited:
                continue
            if len(path_nodes) >= cutoff + 1:
                continue
            if child == dst:
                node_path = path_nodes + [child]
                results.append([(node_path[i], node_path[i + 1]) for i in range(len(node_path) - 1)])
                continue
            visited.add(child)
            path_nodes.append(child)
            stack.append((child, iter(self.network.delta_plus(child))))
        return results


class BaseMappingSolver:
    def __init__(self, network: DistributedComputingNetwork, seed: int = 1, logger: Optional[logging.Logger] = None):
        self.network = network
        self.oracle = DijkstraOracle(network)
        self.random = random.Random(seed)
        self.logger = logger or logging.getLogger(__name__)

    def compute(
        self,
        dag: ServiceDAG,
        commodity: Commodity,
        q_link: Mapping[Edge, float],
        q_node: Mapping[NodeId, float],
    ) -> ValidMapping:
        raise NotImplementedError

    def _edge_cost_fn(self, q_link: Mapping[Edge, float], epsilon: float = 1e-9) -> Callable[[NodeId, NodeId], float]:
        return lambda u, v: float(q_link.get((str(u), str(v)), 0.0)) + epsilon

    def _hop_cost_fn(self) -> Callable[[NodeId, NodeId], float]:
        return lambda u, v: 1.0

    def _build_mapping_from_assignment(
        self,
        dag: ServiceDAG,
        commodity: Commodity,
        assign: Mapping[NodeId, NodeId],
        edge_cost: Callable[[NodeId, NodeId], float],
        q_link: Mapping[Edge, float],
        q_node: Mapping[NodeId, float],
    ) -> ValidMapping:
        vm = ValidMapping(assign={str(k): str(v) for k, v in assign.items()}, total_cost=0.0)

        # source -> function
        for a in dag.sources():
            src_sub = commodity.src_nodes[str(a)]
            dst_u = assign[str(a)]
            _, path = self.oracle.shortest_path(src_sub, dst_u, edge_cost)
            vm.set_edge_path((("S", str(a)), str(a)), path)
            vm.total_cost += dag.xi_source()[str(a)] * sum(q_link.get(e, 0.0) for e in path)

        # function -> function
        for a, b in dag.edges_all():
            ua, ub = assign[str(a)], assign[str(b)]
            _, path = self.oracle.shortest_path(ua, ub, edge_cost)
            vm.set_edge_path((str(a), str(b)), path)
            vm.total_cost += dag.xi(str(a), str(b)) * sum(q_link.get(e, 0.0) for e in path)

        # function -> sink
        for a in dag.sinks():
            ua = assign[str(a)]
            dst_sub = commodity.dst_nodes[str(a)]
            _, path = self.oracle.shortest_path(ua, dst_sub, edge_cost)
            vm.set_edge_path((str(a), ("D", str(a))), path)
            vm.total_cost += dag.xi_sink()[str(a)] * sum(q_link.get(e, 0.0) for e in path)

        for a, u in assign.items():
            vm.total_cost += dag.r(str(a)) * q_node.get(str(u), 0.0)
        return vm


class DynVMPBridgeSolver(BaseMappingSolver):
    """Exact DynVMP solver accessed through an external subprocess bridge.

    This keeps the main simulator in Python 3 while allowing DynVMP to run in a
    separate Python 2.7 environment together with the official ``alib`` and
    ``vnep-approx`` repositories.
    """

    def __init__(
        self,
        network: DistributedComputingNetwork,
        bridge_cmd: Optional[Sequence[str]] = None,
        seed: int = 1,
        keep_io_files: bool = False,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        super().__init__(network, seed=seed, logger=logger)
        if bridge_cmd is None:
            env_cmd = os.environ.get("DCNC_DYNVMP_CMD")
            if not env_cmd:
                raise ValueError(
                    "DynVMP bridge command not specified. Pass bridge_cmd=... or set DCNC_DYNVMP_CMD."
                )
            bridge_cmd = shlex.split(env_cmd)
        self.bridge_cmd = [str(x) for x in bridge_cmd]
        self.keep_io_files = bool(keep_io_files)
        self._bridge_call_counter = 0

    def _payload(
        self,
        dag: ServiceDAG,
        commodity: Commodity,
        q_link: Mapping[Edge, float],
        q_node: Mapping[NodeId, float],
    ) -> Dict[str, Any]:
        return {
            "commodity_name": commodity.name,
            "network": {
                "nodes": [
                    {
                        "id": str(u),
                        "capacity": float(self.network.node_capacity(u)),
                        "queue_cost": float(q_node.get(str(u), 0.0)),
                    }
                    for u in self.network.nodes_all()
                ],
                "edges": [
                    {
                        "tail": str(u),
                        "head": str(v),
                        "capacity": float(self.network.link_capacity(u, v)),
                        "queue_cost": float(q_link.get((str(u), str(v)), 0.0)) + _TIEBREAK_EPS,
                    }
                    for (u, v) in self.network.edges_all()
                ],
            },
            "dag": {
                "functions": [
                    {
                        "id": str(a),
                        "r": float(dag.r(a)),
                        "allowed_nodes": [str(u) for u in commodity.allowed_nodes(self.network, a)],
                    }
                    for a in dag.nodes_all()
                ],
                "edges": [
                    {"tail": str(a), "head": str(b), "xi": float(dag.xi(a, b))}
                    for (a, b) in dag.edges_all()
                ],
                "sources": [
                    {
                        "function": str(a),
                        "physical_node": str(commodity.src_nodes[str(a)]),
                        "xi": float(dag.xi_source()[str(a)]),
                    }
                    for a in dag.sources()
                ],
                "sinks": [
                    {
                        "function": str(a),
                        "physical_node": str(commodity.dst_nodes[str(a)]),
                        "xi": float(dag.xi_sink()[str(a)]),
                    }
                    for a in dag.sinks()
                ],
            },
        }

    def compute(
        self,
        dag: ServiceDAG,
        commodity: Commodity,
        q_link: Mapping[Edge, float],
        q_node: Mapping[NodeId, float],
    ) -> ValidMapping:
        self._bridge_call_counter += 1
        call_id = self._bridge_call_counter
        payload = self._payload(dag, commodity, q_link, q_node)
        tmpdir = tempfile.mkdtemp(prefix="dcnc_dynvmp_")
        input_path = os.path.join(tmpdir, "input.json")
        output_path = os.path.join(tmpdir, "output.json")
        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        cmd = list(self.bridge_cmd) + ["--input", input_path, "--output", output_path]
        result = None
        started = time.perf_counter()
        self.logger.info(
            "[DynVMP] start call=%d commodity=%s dag=%s",
            call_id,
            commodity.name,
            dag.service_chain_id,
        )
        self.logger.debug("[DynVMP] call=%d cmd=%s", call_id, " ".join(cmd))
        self.logger.debug("[DynVMP] call=%d payload=%s", call_id, payload)
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
            with open(output_path, "r", encoding="utf-8") as f:
                result = json.load(f)
        except subprocess.CalledProcessError as e:
            bridge_result = None
            if os.path.exists(output_path):
                try:
                    with open(output_path, "r", encoding="utf-8") as f:
                        bridge_result = json.load(f)
                except Exception:
                    bridge_result = None
            self.logger.error("[DynVMP] failed call=%d returncode=%s", call_id, e.returncode)
            self.logger.error("[DynVMP] failed call=%d stdout=\n%s", call_id, e.stdout)
            self.logger.error("[DynVMP] failed call=%d stderr=\n%s", call_id, e.stderr)
            self.logger.error("[DynVMP] failed call=%d bridge_output=%s", call_id, bridge_result)
            raise RuntimeError(
                "DynVMP subprocess failed.\n"
                "CMD: {}\n\n"
                "STDOUT:\n{}\n\n"
                "STDERR:\n{}\n\n"
                "BRIDGE_OUTPUT_JSON:\n{}".format(
                    " ".join(cmd),
                    e.stdout,
                    e.stderr,
                    bridge_result,
                )
            )
        finally:
            if not self.keep_io_files:
                try:
                    for p in [input_path, output_path]:
                        if os.path.exists(p):
                            os.remove(p)
                    os.rmdir(tmpdir)
                except OSError:
                    pass
        if result.get("status") != "ok":
            self.logger.error("[DynVMP] bridge returned non-ok status on call=%d: %s", call_id, result)
            raise RuntimeError("DynVMP bridge failed: {}".format(result.get("message", "unknown error")))

        vm = ValidMapping(assign={str(k): str(v) for k, v in result["assign"].items()}, total_cost=float(result.get("objective", 0.0)))
        for item in result.get("paths", []):
            kind = item["kind"]
            path = [(str(u), str(v)) for (u, v) in item.get("path", [])]
            if kind == "source":
                a = str(item["function"])
                vm.set_edge_path((("S", a), a), path)
            elif kind == "sink":
                a = str(item["function"])
                vm.set_edge_path((a, ("D", a)), path)
            else:
                vm.set_edge_path((str(item["tail"]), str(item["head"])), path)
        elapsed = time.perf_counter() - started
        self.logger.info(
            "[DynVMP] done call=%d elapsed=%.3fs objective=%.6f",
            call_id,
            elapsed,
            vm.total_cost,
        )
        self.logger.debug("[DynVMP] call=%d assign=%s", call_id, vm.assign)
        return vm


class QueueAwareGreedySolver(BaseMappingSolver):
    """Greedy queue-aware valid-mapping solver for large experiments.

    It keeps the queue-based logic of DCNC-DAG, but uses a topological-order greedy
    assignment instead of DynVMP. This substantially simplifies deployment on a new
    Python 3 server while preserving the core routing intuition.
    """

    def compute(
        self,
        dag: ServiceDAG,
        commodity: Commodity,
        q_link: Mapping[Edge, float],
        q_node: Mapping[NodeId, float],
    ) -> ValidMapping:
        assign: Dict[NodeId, NodeId] = {}
        edge_cost = self._edge_cost_fn(q_link)
        xi_s = dag.xi_source()
        xi_d = dag.xi_sink()
        topo = dag.topo_order()

        for a in topo:
            candidates = commodity.allowed_nodes(self.network, a)
            best_u: Optional[NodeId] = None
            best_cost = math.inf
            for u in candidates:
                local_cost = dag.r(a) * q_node.get(u, 0.0)
                feasible = True
                if a in xi_s:
                    d, _ = self.oracle.shortest_path(commodity.src_nodes[a], u, edge_cost)
                    if math.isinf(d):
                        feasible = False
                    else:
                        local_cost += xi_s[a] * d
                for pred in dag.delta_minus(a):
                    if pred not in assign:
                        continue
                    d, _ = self.oracle.shortest_path(assign[pred], u, edge_cost)
                    if math.isinf(d):
                        feasible = False
                        break
                    local_cost += dag.xi(pred, a) * d
                if not feasible:
                    continue
                if a in xi_d:
                    d, _ = self.oracle.shortest_path(u, commodity.dst_nodes[a], edge_cost)
                    if math.isinf(d):
                        feasible = False
                    else:
                        local_cost += xi_d[a] * d
                if not feasible:
                    continue
                # small tie-break toward shorter hop distance from sources
                if local_cost < best_cost - 1e-12:
                    best_cost = local_cost
                    best_u = u
            if best_u is None:
                # Fallback: ignore queue weights and pick the first reachable candidate.
                for u in candidates:
                    ok = True
                    if a in xi_s:
                        d, _ = self.oracle.shortest_path(commodity.src_nodes[a], u, self._hop_cost_fn())
                        ok &= not math.isinf(d)
                    for pred in dag.delta_minus(a):
                        if pred in assign:
                            d, _ = self.oracle.shortest_path(assign[pred], u, self._hop_cost_fn())
                            ok &= not math.isinf(d)
                    if a in xi_d:
                        d, _ = self.oracle.shortest_path(u, commodity.dst_nodes[a], self._hop_cost_fn())
                        ok &= not math.isinf(d)
                    if ok:
                        best_u = u
                        break
            if best_u is None:
                raise RuntimeError(f"No feasible compute node found for function {a}")
            assign[a] = best_u

        vm = self._build_mapping_from_assignment(dag, commodity, assign, edge_cost, q_link, q_node)
        self.logger.debug("[QueueAwareGreedy] commodity=%s assign=%s cost=%.6f", commodity.name, vm.assign, vm.total_cost)
        return vm


class NearestToSourceSolver(BaseMappingSolver):
    def compute(
        self,
        dag: ServiceDAG,
        commodity: Commodity,
        q_link: Mapping[Edge, float],
        q_node: Mapping[NodeId, float],
    ) -> ValidMapping:
        assign: Dict[NodeId, NodeId] = {}
        hop_cost = self._hop_cost_fn()
        source_nodes = {a: commodity.src_nodes[a] for a in dag.sources()}
        for a in dag.topo_order():
            candidates = commodity.allowed_nodes(self.network, a)
            best_u = None
            best_val = math.inf
            for u in candidates:
                if a in source_nodes:
                    val, _ = self.oracle.shortest_path(source_nodes[a], u, hop_cost)
                else:
                    val = 0.0
                    for s in source_nodes.values():
                        d, _ = self.oracle.shortest_path(s, u, hop_cost)
                        val += d
                if val < best_val:
                    best_val = val
                    best_u = u
            if best_u is None:
                raise RuntimeError(f"CTS found no candidate for {a}")
            assign[a] = best_u
        vm = self._build_mapping_from_assignment(dag, commodity, assign, hop_cost, q_link, q_node)
        self.logger.debug("[NearestToSource] commodity=%s assign=%s cost=%.6f", commodity.name, vm.assign, vm.total_cost)
        return vm


class RandomSolver(BaseMappingSolver):
    def compute(
        self,
        dag: ServiceDAG,
        commodity: Commodity,
        q_link: Mapping[Edge, float],
        q_node: Mapping[NodeId, float],
    ) -> ValidMapping:
        assign: Dict[NodeId, NodeId] = {}
        hop_cost = lambda u, v: 1.0 + self.random.random() * 1e-6
        for a in dag.topo_order():
            candidates = commodity.allowed_nodes(self.network, a)
            self.random.shuffle(candidates)
            selected = None
            for u in candidates:
                ok = True
                if a in dag.xi_source():
                    d, _ = self.oracle.shortest_path(commodity.src_nodes[a], u, hop_cost)
                    ok &= not math.isinf(d)
                for pred in dag.delta_minus(a):
                    if pred in assign:
                        d, _ = self.oracle.shortest_path(assign[pred], u, hop_cost)
                        ok &= not math.isinf(d)
                if a in dag.xi_sink():
                    d, _ = self.oracle.shortest_path(u, commodity.dst_nodes[a], hop_cost)
                    ok &= not math.isinf(d)
                if ok:
                    selected = u
                    break
            if selected is None:
                raise RuntimeError(f"Random solver found no feasible node for {a}")
            assign[a] = selected
        vm = self._build_mapping_from_assignment(dag, commodity, assign, hop_cost, q_link, q_node)
        self.logger.debug("[RandomSolver] commodity=%s assign=%s cost=%.6f", commodity.name, vm.assign, vm.total_cost)
        return vm


class ExactEnumerationSolver(BaseMappingSolver):
    """Exact solver for small graphs used in the boundary-validation experiment."""

    def __init__(self, network: DistributedComputingNetwork, max_assignments: int = 50000, seed: int = 1, logger: Optional[logging.Logger] = None):
        super().__init__(network, seed=seed, logger=logger)
        self.max_assignments = max_assignments

    def compute(
        self,
        dag: ServiceDAG,
        commodity: Commodity,
        q_link: Mapping[Edge, float],
        q_node: Mapping[NodeId, float],
    ) -> ValidMapping:
        edge_cost = self._edge_cost_fn(q_link)
        best: Optional[ValidMapping] = None
        count = 0
        topo = dag.topo_order()

        def backtrack(idx: int, assign: Dict[NodeId, NodeId]) -> None:
            nonlocal best, count
            if count >= self.max_assignments:
                return
            if idx == len(topo):
                count += 1
                vm = self._build_mapping_from_assignment(dag, commodity, assign, edge_cost, q_link, q_node)
                if best is None or vm.total_cost < best.total_cost:
                    best = vm
                return
            a = topo[idx]
            for u in commodity.allowed_nodes(self.network, a):
                # quick feasibility pruning
                feasible = True
                if a in dag.xi_source():
                    d, _ = self.oracle.shortest_path(commodity.src_nodes[a], u, edge_cost)
                    if math.isinf(d):
                        feasible = False
                for pred in dag.delta_minus(a):
                    if pred in assign:
                        d, _ = self.oracle.shortest_path(assign[pred], u, edge_cost)
                        if math.isinf(d):
                            feasible = False
                            break
                if not feasible:
                    continue
                assign[a] = u
                backtrack(idx + 1, assign)
                assign.pop(a, None)

        self.logger.debug("[ExactEnumeration] start commodity=%s dag=%s", commodity.name, dag.service_chain_id)
        backtrack(0, {})
        if best is None:
            raise RuntimeError("ExactEnumerationSolver found no feasible valid mapping")
        self.logger.debug("[ExactEnumeration] done commodity=%s enumerated_assignments=%d best_cost=%.6f assign=%s", commodity.name, count, best.total_cost, best.assign)
        return best



class ExactDPSolver(BaseMappingSolver):
    """Exact minimum-cost valid mapping, solved in-process by bucket elimination.

    This is the same optimisation problem the DynVMP bridge solves.  The bridge
    hands DynVMP soft substrate capacities (see tools/dynvmp_bridge.py), so a
    valid mapping is constrained only by the per-function allowed-node sets and
    by reachability; the objective is then

        sum_a  r(a) * q_node[m(a)]
      + sum_{a in sources} xi_s(a) * d(src(a), m(a))
      + sum_{(a,b) in DAG} xi(a,b) * d(m(a), m(b))
      + sum_{a in sinks}   xi_d(a) * d(m(a), dst(a))

    with d the queue-weighted shortest-path cost.  That is a pairwise MRF over
    the service DAG, so bucket elimination along a min-fill order returns the
    global optimum exactly.  Service DAGs here have induced width 2-3, which
    makes this milliseconds per call instead of the ~5.7 s DynVMP needs.
    """

    def __init__(self, network: DistributedComputingNetwork, seed: int = 1, logger: Optional[logging.Logger] = None):
        super().__init__(network, seed=seed, logger=logger)

    def _dijkstra_dist(self, src: NodeId, edge_cost: Callable[[NodeId, NodeId], float]) -> Dict[NodeId, float]:
        """Full single-source distance map (no path reconstruction)."""
        import heapq

        src = str(src)
        dist: Dict[NodeId, float] = {src: 0.0}
        pq: List[Tuple[float, NodeId]] = [(0.0, src)]
        visited: set = set()
        while pq:
            cur_d, u = heapq.heappop(pq)
            if u in visited:
                continue
            visited.add(u)
            for v in self.network.delta_plus(u):
                nd = cur_d + float(edge_cost(u, v))
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    heapq.heappush(pq, (nd, v))
        return dist

    @staticmethod
    def _min_fill_order(variables: Sequence[NodeId], adj: Mapping[NodeId, set]) -> List[NodeId]:
        """Greedy min-fill elimination order; ties broken by name for determinism."""
        work = {a: set(adj.get(a, ())) for a in variables}
        order: List[NodeId] = []
        remaining = set(variables)
        while remaining:
            best, best_fill, best_deg = None, None, None
            for a in sorted(remaining):
                nbrs = work[a] & remaining
                fill = 0
                nl = sorted(nbrs)
                for i in range(len(nl)):
                    for j in range(i + 1, len(nl)):
                        if nl[j] not in work[nl[i]]:
                            fill += 1
                key_deg = len(nbrs)
                if best is None or (fill, key_deg) < (best_fill, best_deg):
                    best, best_fill, best_deg = a, fill, key_deg
            nbrs = work[best] & remaining
            nl = sorted(nbrs)
            for i in range(len(nl)):
                for j in range(i + 1, len(nl)):
                    work[nl[i]].add(nl[j])
                    work[nl[j]].add(nl[i])
            remaining.discard(best)
            order.append(best)
        return order

    def compute(
        self,
        dag: ServiceDAG,
        commodity: Commodity,
        q_link: Mapping[Edge, float],
        q_node: Mapping[NodeId, float],
    ) -> ValidMapping:
        import numpy as np

        edge_cost = self._edge_cost_fn(q_link)
        variables = [str(a) for a in dag.nodes_all()]
        dom: Dict[NodeId, List[NodeId]] = {}
        for a in variables:
            cand = [str(u) for u in commodity.allowed_nodes(self.network, a)]
            if not cand:
                raise RuntimeError(f"No allowed compute node for function {a}")
            dom[a] = cand
        idx_of = {a: {u: i for i, u in enumerate(dom[a])} for a in variables}

        xi_s = {str(k): float(v) for k, v in dag.xi_source().items()}
        xi_d = {str(k): float(v) for k, v in dag.xi_sink().items()}

        # One Dijkstra per candidate node (covers function->function and
        # function->sink) plus one per distinct source ingress node.
        origins = set()
        for a in variables:
            origins.update(dom[a])
        for a in xi_s:
            origins.add(str(commodity.src_nodes[a]))
        dist_from = {u: self._dijkstra_dist(u, edge_cost) for u in sorted(origins)}

        INF = float("inf")
        factors: List[Tuple[Tuple[NodeId, ...], "np.ndarray"]] = []

        for a in variables:
            tab = np.empty(len(dom[a]), dtype=float)
            src_d = dist_from[str(commodity.src_nodes[a])] if a in xi_s else None
            dst_node = str(commodity.dst_nodes[a]) if a in xi_d else None
            r_a = float(dag.r(a))
            for i, u in enumerate(dom[a]):
                c = r_a * float(q_node.get(u, 0.0))
                if src_d is not None:
                    c += xi_s[a] * src_d.get(u, INF)
                if dst_node is not None:
                    c += xi_d[a] * dist_from[u].get(dst_node, INF)
                tab[i] = c
            factors.append(((a,), tab))

        adj: Dict[NodeId, set] = {a: set() for a in variables}
        for (a, b) in dag.edges_all():
            a, b = str(a), str(b)
            xi_ab = float(dag.xi(a, b))
            tab = np.empty((len(dom[a]), len(dom[b])), dtype=float)
            for i, u in enumerate(dom[a]):
                du = dist_from[u]
                for j, v in enumerate(dom[b]):
                    tab[i, j] = xi_ab * du.get(v, INF)
            factors.append(((a, b), tab))
            adj[a].add(b)
            adj[b].add(a)

        order = self._min_fill_order(variables, adj)
        dsize = {a: len(dom[a]) for a in variables}
        records: List[Tuple[NodeId, Tuple[NodeId, ...], "np.ndarray"]] = []
        const = 0.0

        for x in order:
            involved = [f for f in factors if x in f[0]]
            factors = [f for f in factors if x not in f[0]]
            if not involved:
                continue
            vs: List[NodeId] = []
            for vv, _ in involved:
                for v in vv:
                    if v != x and v not in vs:
                        vs.append(v)
            vs.append(x)
            acc = np.zeros(tuple(dsize[v] for v in vs), dtype=float)
            for vv, tab in involved:
                pos = [vs.index(v) for v in vv]
                perm = sorted(range(len(pos)), key=lambda k: pos[k])
                t = np.transpose(tab, perm)
                shape = [1] * len(vs)
                for k, p in enumerate(sorted(pos)):
                    shape[p] = t.shape[k]
                acc = acc + t.reshape(shape)
            new_vars = tuple(vs[:-1])
            records.append((x, new_vars, np.argmin(acc, axis=-1)))
            reduced = np.min(acc, axis=-1)
            if new_vars:
                factors.append((new_vars, reduced))
            else:
                const += float(reduced)

        for vv, tab in factors:
            if not vv:
                const += float(tab)

        if not math.isfinite(const):
            raise RuntimeError("ExactDPSolver found no feasible valid mapping")

        chosen: Dict[NodeId, int] = {}
        for x, new_vars, amin in reversed(records):
            chosen[x] = int(amin[tuple(chosen[v] for v in new_vars)]) if new_vars else int(amin)
        assign = {a: dom[a][chosen[a]] for a in variables}

        vm = self._build_mapping_from_assignment(dag, commodity, assign, edge_cost, q_link, q_node)
        self.logger.debug("[ExactDP] commodity=%s assign=%s cost=%.6f", commodity.name, vm.assign, vm.total_cost)
        return vm

class StaticPlacementSolver(BaseMappingSolver):
    """Static placement baseline used for computation-graph experiments.

    A single mapping is computed once using hop-based costs and then reused for every arrival.
    This approximates a structure-aware but queue-unaware baseline.
    """

    def __init__(self, network: DistributedComputingNetwork, seed: int = 1, logger: Optional[logging.Logger] = None):
        super().__init__(network, seed=seed, logger=logger)
        self._cache: Dict[Tuple[str, str], ValidMapping] = {}

    def compute(
        self,
        dag: ServiceDAG,
        commodity: Commodity,
        q_link: Mapping[Edge, float],
        q_node: Mapping[NodeId, float],
    ) -> ValidMapping:
        key = (commodity.name, dag.service_chain_id)
        if key not in self._cache:
            assign: Dict[NodeId, NodeId] = {}
            hop_cost = self._hop_cost_fn()
            for a in dag.topo_order():
                candidates = commodity.allowed_nodes(self.network, a)
                best_u = None
                best_score = math.inf
                for u in candidates:
                    score = dag.r(a) / max(self.network.node_capacity(u), 1e-9)
                    if a in dag.xi_source():
                        d, _ = self.oracle.shortest_path(commodity.src_nodes[a], u, hop_cost)
                        score += d
                    for pred in dag.delta_minus(a):
                        if pred in assign:
                            d, _ = self.oracle.shortest_path(assign[pred], u, hop_cost)
                            score += d
                    if a in dag.xi_sink():
                        d, _ = self.oracle.shortest_path(u, commodity.dst_nodes[a], hop_cost)
                        score += d
                    if score < best_score:
                        best_score = score
                        best_u = u
                if best_u is None:
                    raise RuntimeError(f"StaticPlacementSolver found no candidate for {a}")
                assign[a] = best_u
            self._cache[key] = self._build_mapping_from_assignment(dag, commodity, assign, hop_cost, q_link, q_node)
        self.logger.debug("[StaticPlacement] commodity=%s assign=%s cost=%.6f", commodity.name, self._cache[key].assign, self._cache[key].total_cost)
        return self._cache[key]


class LeastUsedReplicaSolver(BaseMappingSolver):
    """Traffic-only replica balancing baseline for MoE-style experiments."""

    def __init__(self, network: DistributedComputingNetwork, seed: int = 1, logger: Optional[logging.Logger] = None):
        super().__init__(network, seed=seed, logger=logger)
        self.usage: Dict[Tuple[str, str], int] = defaultdict(int)

    def compute(
        self,
        dag: ServiceDAG,
        commodity: Commodity,
        q_link: Mapping[Edge, float],
        q_node: Mapping[NodeId, float],
    ) -> ValidMapping:
        assign: Dict[NodeId, NodeId] = {}
        hop_cost = self._hop_cost_fn()
        for a in dag.topo_order():
            candidates = commodity.allowed_nodes(self.network, a)
            best_u = min(candidates, key=lambda u: (self.usage[(a, u)], self.random.random()))
            assign[a] = best_u
            self.usage[(a, best_u)] += 1
        vm = self._build_mapping_from_assignment(dag, commodity, assign, hop_cost, q_link, q_node)
        self.logger.debug("[LeastUsedReplica] commodity=%s assign=%s cost=%.6f", commodity.name, vm.assign, vm.total_cost)
        return vm


class RoundRobinReplicaSolver(BaseMappingSolver):
    def __init__(self, network: DistributedComputingNetwork, seed: int = 1, logger: Optional[logging.Logger] = None):
        super().__init__(network, seed=seed, logger=logger)
        self.ptr: Dict[str, int] = defaultdict(int)

    def compute(
        self,
        dag: ServiceDAG,
        commodity: Commodity,
        q_link: Mapping[Edge, float],
        q_node: Mapping[NodeId, float],
    ) -> ValidMapping:
        assign: Dict[NodeId, NodeId] = {}
        hop_cost = self._hop_cost_fn()
        for a in dag.topo_order():
            candidates = sorted(commodity.allowed_nodes(self.network, a))
            if not candidates:
                raise RuntimeError(f"No candidates for {a}")
            idx = self.ptr[a] % len(candidates)
            assign[a] = candidates[idx]
            self.ptr[a] += 1
        vm = self._build_mapping_from_assignment(dag, commodity, assign, hop_cost, q_link, q_node)
        self.logger.debug("[RoundRobinReplica] commodity=%s assign=%s cost=%.6f", commodity.name, vm.assign, vm.total_cost)
        return vm


class FixedMappingSolver(BaseMappingSolver):
    def __init__(self, network: DistributedComputingNetwork, fixed_assignment: Mapping[NodeId, NodeId], logger: Optional[logging.Logger] = None):
        super().__init__(network, seed=1, logger=logger)
        self.fixed_assignment = {str(k): str(v) for k, v in fixed_assignment.items()}

    def compute(
        self,
        dag: ServiceDAG,
        commodity: Commodity,
        q_link: Mapping[Edge, float],
        q_node: Mapping[NodeId, float],
    ) -> ValidMapping:
        vm = self._build_mapping_from_assignment(
            dag,
            commodity,
            self.fixed_assignment,
            self._hop_cost_fn(),
            q_link,
            q_node,
        )
        self.logger.debug("[FixedMapping] commodity=%s assign=%s cost=%.6f", commodity.name, vm.assign, vm.total_cost)
        return vm


def enumerate_all_valid_mappings_small(
    network: DistributedComputingNetwork,
    dag: ServiceDAG,
    commodity: Commodity,
) -> List[ValidMapping]:
    """Enumerate all valid mappings for a small graph.

    This routine is intended only for the theoretical-boundary validation example.
    It enumerates node assignments and all simple paths for every dependency.
    """
    oracle = DijkstraOracle(network)
    topo = dag.topo_order()
    mappings: List[ValidMapping] = []

    def backtrack_assign(idx: int, assign: Dict[NodeId, NodeId]) -> None:
        if idx == len(topo):
            build_all_path_combinations(assign)
            return
        a = topo[idx]
        for u in commodity.allowed_nodes(network, a):
            # basic reachability pruning
            ok = True
            if a in dag.xi_source():
                d, _ = oracle.shortest_path(commodity.src_nodes[a], u, lambda x, y: 1.0)
                ok &= not math.isinf(d)
            for pred in dag.delta_minus(a):
                if pred in assign:
                    d, _ = oracle.shortest_path(assign[pred], u, lambda x, y: 1.0)
                    ok &= not math.isinf(d)
            if a in dag.xi_sink():
                d, _ = oracle.shortest_path(u, commodity.dst_nodes[a], lambda x, y: 1.0)
                ok &= not math.isinf(d)
            if not ok:
                continue
            assign[a] = u
            backtrack_assign(idx + 1, assign)
            assign.pop(a, None)

    def build_all_path_combinations(assign: Dict[NodeId, NodeId]) -> None:
        keys: List[MappingEdgeKey] = []
        path_options: List[List[List[Edge]]] = []

        for a in dag.sources():
            src_u = commodity.src_nodes[a]
            dst_u = assign[a]
            keys.append((("S", a), a))
            path_options.append(oracle.all_simple_paths(src_u, dst_u))
        for a, b in dag.edges_all():
            keys.append((a, b))
            path_options.append(oracle.all_simple_paths(assign[a], assign[b]))
        for a in dag.sinks():
            keys.append((a, ("D", a)))
            path_options.append(oracle.all_simple_paths(assign[a], commodity.dst_nodes[a]))

        for combo in itertools.product(*path_options):
            vm = ValidMapping(assign=dict(assign), total_cost=0.0)
            for key, path in zip(keys, combo):
                vm.set_edge_path(key, path)
            mappings.append(vm)

    backtrack_assign(0, {})
    return mappings
