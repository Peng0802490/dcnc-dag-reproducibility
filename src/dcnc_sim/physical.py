from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from .mapping import ValidMapping
from .models import Commodity, DistributedComputingNetwork, Edge, NodeId, ServiceDAG
from .wireless import BaseLinkStateProcess


@dataclass(slots=True)
class LinkQueueItem:
    commodity_name: str
    job_id: str
    edge_key: tuple[Any, Any]
    path: list[Edge]
    path_index: int
    flow_size: float
    size_remaining: float
    hop: int
    enqueue_seq: int

    def current_edge(self) -> Optional[Edge]:
        if self.path_index < len(self.path):
            return self.path[self.path_index]
        return None

    def finish_edge(self) -> None:
        self.path_index += 1
        self.hop += 1
        if self.path_index < len(self.path):
            # Each physical hop of the mapped path consumes the same amount of
            # transmission service. Reset the residual size for the next hop.
            self.size_remaining = self.flow_size

    def is_path_done(self) -> bool:
        return self.path_index >= len(self.path)


@dataclass(slots=True)
class ComputeTask:
    commodity_name: str
    job_id: str
    func: NodeId
    node: NodeId
    size_remaining: float
    hop: int
    mapping: ValidMapping
    dag: ServiceDAG
    enqueue_seq: int

    def finish_processing(self) -> None:
        self.hop += 1


@dataclass
class PhysicalNetwork:
    network: DistributedComputingNetwork
    wireless_process: BaseLinkStateProcess
    scheduler: str = "nto"
    unfinished_penalty: float = 100000.0

    link_queues: Dict[Edge, List[LinkQueueItem]] = field(init=False)
    node_queues: Dict[NodeId, List[ComputeTask]] = field(init=False)
    wait_pools: Dict[Tuple[NodeId, NodeId], Dict[str, Dict[str, Any]]] = field(default_factory=dict)
    current_time: int = 0
    current_link_capacities: Dict[Edge, float] = field(default_factory=dict)
    activated_edges: Set[Edge] = field(default_factory=set)
    _enqueue_seq: int = 0

    delivered_packets: int = 0
    total_packets: int = 0
    pending_packets: int = 0
    delay_sum_completed: float = 0.0
    completed_service_units: int = 0
    total_service_units: int = 0
    service_delay_sum_completed: float = 0.0
    job_born_time: Dict[str, int] = field(default_factory=dict)
    job_inject_time: Dict[str, int] = field(default_factory=dict)
    job_remaining_sinks: Dict[str, int] = field(default_factory=dict)
    job_ctx: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    packet_control_wait_sum_completed: float = 0.0
    packet_network_delay_sum_completed: float = 0.0
    service_control_wait_sum_completed: float = 0.0
    service_network_delay_sum_completed: float = 0.0

    def __post_init__(self) -> None:
        self.scheduler = self.scheduler.lower()
        self.link_queues = {e: [] for e in self.network.edges_all()}
        self.node_queues = {u: [] for u in self.network.nodes_all()}
        self.current_link_capacities = self.wireless_process.sample_capacities(0)
        self.activated_edges = {e for e, cap in self.current_link_capacities.items() if float(cap) > 1e-12}

    def set_time(self, slot: int) -> None:
        self.current_time = int(slot)
        self.current_link_capacities = self.wireless_process.sample_capacities(slot)
        # Default behavior: if the simulator does not override the activation
        # decision, every ON link remains active.
        self.activated_edges = {e for e, cap in self.current_link_capacities.items() if float(cap) > 1e-12}

    def set_activated_edges(self, edges: Set[Edge]) -> None:
        on_edges = {e for e, cap in self.current_link_capacities.items() if float(cap) > 1e-12}
        self.activated_edges = {tuple(map(str, e)) for e in edges if tuple(map(str, e)) in on_edges}

    def effective_link_service_map(self) -> Dict[Edge, float]:
        return {
            e: float(self.current_link_capacities.get(e, 0.0)) if e in self.activated_edges else 0.0
            for e in self.network.edges_all()
        }

    def active_edge_count(self) -> int:
        return len(self.activated_edges)

    def _next_seq(self) -> int:
        self._enqueue_seq += 1
        return self._enqueue_seq

    def register_job(
        self,
        job_id: str,
        mapping: ValidMapping,
        dag: ServiceDAG,
        commodity: Commodity,
        born_time: int,
        inject_time: Optional[int] = None,
    ) -> None:
        self.job_ctx[job_id] = {
            "mapping": mapping,
            "dag": dag,
            "commodity": commodity,
            "xi_s": dag.xi_source(),
            "xi_d": dag.xi_sink(),
            "preds": {a: set(dag.delta_minus(a)) for a in dag.nodes_all()},
        }
        self.job_born_time[job_id] = int(born_time)
        self.job_inject_time[job_id] = int(self.current_time if inject_time is None else inject_time)
        num_sinks = len(dag.sinks())
        self.job_remaining_sinks[job_id] = num_sinks
        self.total_packets += num_sinks
        self.pending_packets += num_sinks
        self.total_service_units += 1

    def _ctx(self, job_id: str) -> Dict[str, Any]:
        return self.job_ctx[job_id]

    def _enqueue_link_item(self, item: LinkQueueItem) -> None:
        edge = item.current_edge()
        if edge is None:
            self._on_path_end(item)
            return
        item.enqueue_seq = self._next_seq()
        self.link_queues[edge].append(item)

    def _enqueue_compute_task(self, task: ComputeTask) -> None:
        task.enqueue_seq = self._next_seq()
        self.node_queues[task.node].append(task)

    def edge_backlog_loads(self) -> Dict[Edge, float]:
        return {e: float(sum(max(0.0, item.size_remaining) for item in q)) for e, q in self.link_queues.items()}

    def _pred_keys_for_func(self, dag: ServiceDAG, func: NodeId) -> set[Any]:
        preds: set[Any] = set(dag.delta_minus(func))
        if func in dag.sources():
            preds.add(("S", func))
        return preds

    def _get_pool_record(self, node: NodeId, func: NodeId, job_id: str) -> Dict[str, Any]:
        key = (node, func)
        table = self.wait_pools.setdefault(key, {})
        if job_id not in table:
            table[job_id] = {"needed": self._pred_keys_for_func(self._ctx(job_id)["dag"], func), "arrived": {}}
        return table[job_id]

    def _maybe_release_task(self, node: NodeId, func: NodeId, job_id: str) -> None:
        key = (node, func)
        rec = self.wait_pools.get(key, {}).get(job_id)
        if rec is None or rec["needed"]:
            return
        ctx = self._ctx(job_id)
        hop_in = max(rec["arrived"].values()) if rec["arrived"] else 0
        task = ComputeTask(
            commodity_name=ctx["commodity"].name,
            job_id=job_id,
            func=func,
            node=node,
            size_remaining=ctx["dag"].r(func),
            hop=hop_in,
            mapping=ctx["mapping"],
            dag=ctx["dag"],
            enqueue_seq=self._next_seq(),
        )
        self._enqueue_compute_task(task)
        del self.wait_pools[key][job_id]
        if not self.wait_pools[key]:
            del self.wait_pools[key]

    def _on_sink_completion(self, job_id: str) -> None:
        self.delivered_packets += 1
        t_born = self.job_born_time.get(job_id, self.current_time)
        t_inject = self.job_inject_time.get(job_id, t_born)
        e2e_delay = float(self.current_time - t_born)
        control_wait = float(max(0, t_inject - t_born))
        network_delay = float(self.current_time - t_inject)
        self.delay_sum_completed += e2e_delay
        self.packet_control_wait_sum_completed += control_wait
        self.packet_network_delay_sum_completed += network_delay
        self.pending_packets -= 1
        self.job_remaining_sinks[job_id] -= 1
        if self.job_remaining_sinks[job_id] <= 0:
            self.completed_service_units += 1
            self.service_delay_sum_completed += e2e_delay
            self.service_control_wait_sum_completed += control_wait
            self.service_network_delay_sum_completed += network_delay
            self.job_remaining_sinks.pop(job_id, None)
            self.job_born_time.pop(job_id, None)
            self.job_inject_time.pop(job_id, None)
            self.job_ctx.pop(job_id, None)

    def _on_path_end(self, item: LinkQueueItem) -> None:
        left, right = item.edge_key
        if isinstance(left, tuple) and left[0] == "S":
            func = left[1]
            ctx = self._ctx(item.job_id)
            node = ctx["mapping"].assign[func]
            rec = self._get_pool_record(node, func, item.job_id)
            rec["arrived"][("S", func)] = item.hop
            rec["needed"].discard(("S", func))
            self._maybe_release_task(node, func, item.job_id)
            return
        if isinstance(right, tuple) and right[0] == "D":
            self._on_sink_completion(item.job_id)
            return
        pred_func = left
        func = right
        ctx = self._ctx(item.job_id)
        node = ctx["mapping"].assign[func]
        rec = self._get_pool_record(node, func, item.job_id)
        rec["arrived"][pred_func] = item.hop
        rec["needed"].discard(pred_func)
        self._maybe_release_task(node, func, item.job_id)

    def inject_one_unit(self, job_id: str) -> None:
        ctx = self._ctx(job_id)
        dag: ServiceDAG = ctx["dag"]
        mapping: ValidMapping = ctx["mapping"]
        xi_s = dag.xi_source()
        for func in dag.sources():
            path = mapping.path_for((("S", func), func))
            item = LinkQueueItem(
                commodity_name=ctx["commodity"].name,
                job_id=job_id,
                edge_key=(("S", func), func),
                path=path,
                path_index=0,
                flow_size=xi_s[func],
                size_remaining=xi_s[func],
                hop=0,
                enqueue_seq=0,
            )
            self._enqueue_link_item(item)

    def _select_index(self, queue: list[Any], candidates: Optional[List[int]] = None) -> int:
        indices = candidates if candidates is not None else list(range(len(queue)))
        if self.scheduler == "fifo":
            return min(indices, key=lambda i: queue[i].enqueue_seq)
        return min(indices, key=lambda i: (queue[i].hop, queue[i].enqueue_seq))

    def _serve_links_one_slot(self) -> None:
        service_map = self.effective_link_service_map()
        start_cutoff = {edge: max((item.enqueue_seq for item in queue), default=0) for edge, queue in self.link_queues.items()}
        for edge, queue in self.link_queues.items():
            budget = float(service_map.get(edge, 0.0))
            cutoff = start_cutoff[edge]
            while budget > 1e-12 and queue:
                eligible = [i for i, item in enumerate(queue) if item.enqueue_seq <= cutoff]
                if not eligible:
                    break
                idx = self._select_index(queue, eligible)
                item = queue[idx]
                take = min(budget, item.size_remaining)
                item.size_remaining -= take
                budget -= take
                if item.size_remaining <= 1e-12:
                    item.finish_edge()
                    queue.pop(idx)
                    if item.is_path_done():
                        self._on_path_end(item)
                    else:
                        self._enqueue_link_item(item)

    def _serve_nodes_one_slot(self) -> None:
        start_cutoff = {node: max((task.enqueue_seq for task in queue), default=0) for node, queue in self.node_queues.items()}
        for node, queue in self.node_queues.items():
            budget = self.network.node_capacity(node)
            cutoff = start_cutoff[node]
            while budget > 1e-12 and queue:
                eligible = [i for i, task in enumerate(queue) if task.enqueue_seq <= cutoff]
                if not eligible:
                    break
                idx = self._select_index(queue, eligible)
                task = queue[idx]
                take = min(budget, task.size_remaining)
                task.size_remaining -= take
                budget -= take
                if task.size_remaining <= 1e-12:
                    queue.pop(idx)
                    task.finish_processing()
                    dag = task.dag
                    mapping = task.mapping
                    hop_now = task.hop
                    for succ in dag.delta_plus(task.func):
                        path = mapping.path_for((task.func, succ))
                        flow = dag.xi(task.func, succ)
                        item = LinkQueueItem(
                            commodity_name=task.commodity_name,
                            job_id=task.job_id,
                            edge_key=(task.func, succ),
                            path=path,
                            path_index=0,
                            flow_size=flow,
                            size_remaining=flow,
                            hop=hop_now,
                            enqueue_seq=0,
                        )
                        self._enqueue_link_item(item)
                    if task.func in dag.sinks():
                        path = mapping.path_for((task.func, ("D", task.func)))
                        flow = dag.xi_sink()[task.func]
                        item = LinkQueueItem(
                            commodity_name=task.commodity_name,
                            job_id=task.job_id,
                            edge_key=(task.func, ("D", task.func)),
                            path=path,
                            path_index=0,
                            flow_size=flow,
                            size_remaining=flow,
                            hop=hop_now,
                            enqueue_seq=0,
                        )
                        self._enqueue_link_item(item)

    def serve_one_slot(self) -> None:
        self._serve_links_one_slot()
        self._serve_nodes_one_slot()

    def total_backlog(self) -> int:
        waiting = sum(len(tbl) for tbl in self.wait_pools.values())
        link_items = sum(len(q) for q in self.link_queues.values())
        node_items = sum(len(q) for q in self.node_queues.values())
        return waiting + link_items + node_items

    def average_delay_completed(self) -> float:
        return self.delay_sum_completed / self.delivered_packets if self.delivered_packets > 0 else 0.0

    def average_delay_with_penalty(self) -> float:
        total = self.delivered_packets + self.pending_packets
        if total <= 0:
            return 0.0
        return (self.delay_sum_completed + self.unfinished_penalty * self.pending_packets) / total

    def pending_service_units(self) -> int:
        return int(self.total_service_units - self.completed_service_units)

    def average_service_delay_completed(self) -> float:
        if self.completed_service_units <= 0:
            return 0.0
        return self.service_delay_sum_completed / self.completed_service_units

    def average_packet_control_wait_completed(self) -> float:
        return self.packet_control_wait_sum_completed / self.delivered_packets if self.delivered_packets > 0 else 0.0

    def average_packet_network_delay_completed(self) -> float:
        return self.packet_network_delay_sum_completed / self.delivered_packets if self.delivered_packets > 0 else 0.0

    def average_service_control_wait_completed(self) -> float:
        return self.service_control_wait_sum_completed / self.completed_service_units if self.completed_service_units > 0 else 0.0

    def average_service_network_delay_completed(self) -> float:
        return self.service_network_delay_sum_completed / self.completed_service_units if self.completed_service_units > 0 else 0.0
