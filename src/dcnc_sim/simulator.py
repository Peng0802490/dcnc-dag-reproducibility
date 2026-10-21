from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import logging
import math
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .interference import BaseActivationPolicy, NoInterferenceActivationPolicy
from .mapping import BaseMappingSolver, ValidMapping
from .models import Commodity, DistributedComputingNetwork, Edge, NodeId
from .physical import PhysicalNetwork
from .virtual import VirtualQueues
from .wireless import BaseLinkStateProcess


@dataclass
class CommodityConfig:
    commodity: Commodity
    arrival_rate: float
    solver: BaseMappingSolver


@dataclass
class SimulationStats:
    delivered_packets: int = 0
    pending_packets: int = 0
    total_packets: int = 0
    avg_delay_completed: float = 0.0
    avg_delay_with_penalty: float = 0.0
    completed_service_units: int = 0
    total_service_units: int = 0
    pending_service_units: int = 0
    avg_service_delay_completed: float = 0.0
    avg_service_delay_with_penalty: float = 0.0

    # Delay decomposition.  Packet-level metrics are kept for compatibility
    # with the paper plots; service-level metrics are usually easier to report
    # for a complete DAG request.
    avg_packet_control_wait_completed: float = 0.0
    avg_packet_network_delay_completed: float = 0.0
    avg_service_control_wait_completed: float = 0.0
    avg_service_network_delay_completed: float = 0.0

    vq_link_sum_series: List[float] = field(default_factory=list)
    vq_node_sum_series: List[float] = field(default_factory=list)
    physical_backlog_series: List[int] = field(default_factory=list)
    activated_edge_count_series: List[int] = field(default_factory=list)

    routing_oracle_calls: int = 0
    routing_cache_hits: int = 0
    routing_oracle_wall_time_sec: float = 0.0
    routing_oracle_runtime_samples_sec: List[float] = field(default_factory=list)
    simulation_wall_time_sec: float = 0.0

    # Runtime-aware asynchronous mapping statistics.
    async_mapping_updates: int = 0
    async_refresh_triggers: int = 0
    async_reuse_service_units: int = 0
    async_cold_start_buffered_service_units: int = 0
    async_control_wait_sum_slots_injected: float = 0.0
    async_control_wait_avg_slots_injected: float = 0.0
    async_control_wait_p95_slots_injected: float = 0.0
    async_control_wait_max_slots_injected: float = 0.0
    async_effective_update_interval_avg_slots: float = 0.0
    async_mapping_age_avg_slots: float = 0.0
    async_mapping_age_max_slots: float = 0.0
    async_controller_utilization: float = 0.0
    async_controller_queue_wait_sum_slots: float = 0.0

    control_buffer_sum_series: List[int] = field(default_factory=list)
    mapping_age_avg_series: List[float] = field(default_factory=list)
    mapping_age_max_series: List[float] = field(default_factory=list)

    oracle_job_records: List[Dict[str, Any]] = field(default_factory=list)
    timeseries_records: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class _PendingRequest:
    job_id: str
    born_slot: int


@dataclass(slots=True)
class _AsyncOracleJob:
    oracle_job_id: int
    key: Tuple[str, str]
    commodity_name: str
    dag_id: str
    reason: str
    trigger_slot: int
    compute_start_slot: int
    ready_slot: int
    runtime_sec: float
    runtime_slots: int
    controller_wait_slots: int
    worker_id: int
    q_link_sum_at_trigger: float
    q_node_sum_at_trigger: float
    mapping_cost: float
    mapping: ValidMapping


@dataclass
class _AsyncCommodityState:
    current_mapping: Optional[ValidMapping] = None
    current_mapping_ready_slot: Optional[int] = None
    current_mapping_snapshot_slot: Optional[int] = None
    current_mapping_job_id: Optional[int] = None
    pending_job: Optional[_AsyncOracleJob] = None
    cold_buffer: List[_PendingRequest] = field(default_factory=list)
    update_slots: List[int] = field(default_factory=list)


@dataclass
class DCNCSimulator:
    network: DistributedComputingNetwork
    commodity_cfgs: Sequence[CommodityConfig]
    wireless_process: BaseLinkStateProcess
    total_slots: int
    seed: int = 1
    scheduler: str = "nto"
    activation_policy: Optional[BaseActivationPolicy] = None
    fixed_k: int = 1
    arrival_mode: str = "poisson"
    logger: Optional[logging.Logger] = None
    run_label: str = ""
    progress_every: Optional[int] = None
    activation_tie_break_eps: float = 1e-6

    # routing_mode="fixed_k" keeps the original implementation.  routing_mode
    # in {"async_refresh", "async"} enables runtime-aware asynchronous DynVMP
    # refresh: cold-start requests wait until the first mapping is ready; later
    # requests reuse the latest ready mapping while a new mapping is computed.
    routing_mode: str = "fixed_k"
    slot_sec: float = 0.01
    oracle_workers: int = 1
    oracle_min_delay_slots: int = 1
    async_refresh_policy: str = "continuous"  # continuous | on_arrival | none
    record_timeseries: bool = False

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        self.virtual_queues = VirtualQueues(self.network, self.wireless_process.average_capacities())
        self.physical_network = PhysicalNetwork(self.network, self.wireless_process, scheduler=self.scheduler)
        self.activation_policy = self.activation_policy or NoInterferenceActivationPolicy()
        self.fixed_k = max(1, int(self.fixed_k))
        self.arrival_mode = str(self.arrival_mode).strip().lower()
        if self.arrival_mode not in {"poisson", "bounded"}:
            raise ValueError(f"unknown arrival_mode: {self.arrival_mode}")
        self.routing_mode = str(self.routing_mode).strip().lower().replace("-", "_")
        if self.routing_mode == "async":
            self.routing_mode = "async_refresh"
        if self.routing_mode not in {"fixed_k", "async_refresh"}:
            raise ValueError(f"unknown routing_mode: {self.routing_mode}")
        self.async_refresh_policy = str(self.async_refresh_policy).strip().lower().replace("-", "_")
        if self.async_refresh_policy not in {"continuous", "on_arrival", "none"}:
            raise ValueError(f"unknown async_refresh_policy: {self.async_refresh_policy}")
        self.slot_sec = float(self.slot_sec)
        if self.slot_sec <= 0:
            raise ValueError("slot_sec must be positive")
        self.oracle_workers = max(1, int(self.oracle_workers))
        self.oracle_min_delay_slots = max(0, int(self.oracle_min_delay_slots))

        self._frame_q_link: Optional[Dict[Edge, float]] = None
        self._frame_q_node: Optional[Dict[NodeId, float]] = None
        self._frame_mapping_cache: Dict[Tuple[str, str], ValidMapping] = {}
        self._job_counter = 0
        self._routing_oracle_calls = 0
        self._routing_cache_hits = 0
        self._routing_oracle_wall_time_sec = 0.0
        self._routing_oracle_runtime_samples_sec: List[float] = []

        self._async_state: Dict[Tuple[str, str], _AsyncCommodityState] = {}
        self._async_ready_heap: List[Tuple[int, int, Tuple[str, str], _AsyncOracleJob]] = []
        self._async_oracle_job_seq = 0
        self._oracle_worker_free_slots: List[int] = [0 for _ in range(self.oracle_workers)]
        self._oracle_job_records: List[Dict[str, Any]] = []
        self._control_wait_samples_injected: List[float] = []
        self._mapping_age_samples: List[float] = []
        self._timeseries_records: List[Dict[str, Any]] = []
        self._async_mapping_updates = 0
        self._async_refresh_triggers = 0
        self._async_reuse_service_units = 0
        self._async_cold_start_buffered_service_units = 0
        self._async_controller_queue_wait_sum_slots = 0.0
        self._generated_service_units = 0

        self.logger = self.logger or logging.getLogger(__name__)
        if self.progress_every is None or self.progress_every <= 0:
            self.progress_every = max(1, self.total_slots // 10)

    def _new_job_id(self, slot: int) -> str:
        self._job_counter += 1
        return f"t{slot}-{self._job_counter}"

    def _sample_arrivals(self, arrival_rate: float) -> int:
        rate = max(0.0, float(arrival_rate))
        if self.arrival_mode == "poisson":
            return int(self.rng.poisson(rate))
        base = int(np.floor(rate))
        frac = rate - base
        return base + int(self.rng.random() < frac)

    @staticmethod
    def _cache_key(cfg: CommodityConfig) -> Tuple[str, str]:
        return (cfg.commodity.name, cfg.commodity.service_dag.service_chain_id)

    def _refresh_fixed_k_frame_if_needed(
        self,
        slot: int,
        q_link_start: Mapping[Edge, float],
        q_node_start: Mapping[NodeId, float],
    ) -> None:
        if self.fixed_k <= 1:
            return
        if self._frame_q_link is None or slot % self.fixed_k == 0:
            self._frame_q_link = dict(q_link_start)
            self._frame_q_node = dict(q_node_start)
            self._frame_mapping_cache = {}
            self.logger.debug(
                "slot=%d | fixed-K frame head | K=%d | frame snapshot refreshed",
                slot,
                self.fixed_k,
            )

    def _compute_mapping_with_runtime(
        self,
        cfg: CommodityConfig,
        q_link_ref: Mapping[Edge, float],
        q_node_ref: Mapping[NodeId, float],
    ) -> Tuple[ValidMapping, float]:
        self._routing_oracle_calls += 1
        started = time.perf_counter()
        mapping = cfg.solver.compute(cfg.commodity.service_dag, cfg.commodity, q_link_ref, q_node_ref)
        elapsed = time.perf_counter() - started
        self._routing_oracle_wall_time_sec += elapsed
        self._routing_oracle_runtime_samples_sec.append(elapsed)
        return mapping, elapsed

    def _compute_mapping(
        self,
        cfg: CommodityConfig,
        q_link_ref: Mapping[Edge, float],
        q_node_ref: Mapping[NodeId, float],
    ) -> ValidMapping:
        mapping, _ = self._compute_mapping_with_runtime(cfg, q_link_ref, q_node_ref)
        return mapping

    def _routing_mapping_for_slot(
        self,
        slot: int,
        cfg: CommodityConfig,
        q_link_start: Mapping[Edge, float],
        q_node_start: Mapping[NodeId, float],
    ) -> ValidMapping:
        if self.fixed_k <= 1:
            return self._compute_mapping(cfg, q_link_start, q_node_start)

        self._refresh_fixed_k_frame_if_needed(slot, q_link_start, q_node_start)
        assert self._frame_q_link is not None
        assert self._frame_q_node is not None
        key = self._cache_key(cfg)
        if key not in self._frame_mapping_cache:
            self._frame_mapping_cache[key] = self._compute_mapping(cfg, self._frame_q_link, self._frame_q_node)
            self.logger.debug(
                "slot=%d | fixed-K compute | commodity=%s | frame_head=%d",
                slot,
                cfg.commodity.name,
                (slot // self.fixed_k) * self.fixed_k,
            )
        else:
            self._routing_cache_hits += 1
            self.logger.debug(
                "slot=%d | fixed-K reuse | commodity=%s | frame_head=%d",
                slot,
                cfg.commodity.name,
                (slot // self.fixed_k) * self.fixed_k,
            )
        return self._frame_mapping_cache[key]

    def _state_for(self, cfg: CommodityConfig) -> _AsyncCommodityState:
        key = self._cache_key(cfg)
        if key not in self._async_state:
            self._async_state[key] = _AsyncCommodityState()
        return self._async_state[key]

    def _runtime_to_slots(self, runtime_sec: float) -> int:
        return max(self.oracle_min_delay_slots, int(math.ceil(max(0.0, runtime_sec) / self.slot_sec)))

    def _launch_async_oracle_job(
        self,
        slot: int,
        cfg: CommodityConfig,
        q_link_ref: Mapping[Edge, float],
        q_node_ref: Mapping[NodeId, float],
        reason: str,
    ) -> Optional[_AsyncOracleJob]:
        key = self._cache_key(cfg)
        state = self._state_for(cfg)
        if state.pending_job is not None:
            return None

        worker_id = min(range(self.oracle_workers), key=lambda i: self._oracle_worker_free_slots[i])
        compute_start_slot = max(int(slot), int(self._oracle_worker_free_slots[worker_id]))
        controller_wait_slots = max(0, compute_start_slot - int(slot))

        mapping, runtime_sec = self._compute_mapping_with_runtime(cfg, q_link_ref, q_node_ref)
        runtime_slots = self._runtime_to_slots(runtime_sec)
        ready_slot = compute_start_slot + runtime_slots
        self._oracle_worker_free_slots[worker_id] = ready_slot

        self._async_oracle_job_seq += 1
        job = _AsyncOracleJob(
            oracle_job_id=self._async_oracle_job_seq,
            key=key,
            commodity_name=cfg.commodity.name,
            dag_id=cfg.commodity.service_dag.service_chain_id,
            reason=str(reason),
            trigger_slot=int(slot),
            compute_start_slot=compute_start_slot,
            ready_slot=ready_slot,
            runtime_sec=float(runtime_sec),
            runtime_slots=int(runtime_slots),
            controller_wait_slots=int(controller_wait_slots),
            worker_id=int(worker_id),
            q_link_sum_at_trigger=float(sum(q_link_ref.values())),
            q_node_sum_at_trigger=float(sum(q_node_ref.values())),
            mapping_cost=float(mapping.total_cost),
            mapping=mapping,
        )
        state.pending_job = job
        heapq.heappush(self._async_ready_heap, (job.ready_slot, job.oracle_job_id, key, job))
        self._async_refresh_triggers += 1
        self._async_controller_queue_wait_sum_slots += float(controller_wait_slots)

        record = {
            "oracle_job_id": job.oracle_job_id,
            "commodity": job.commodity_name,
            "dag_id": job.dag_id,
            "reason": job.reason,
            "trigger_slot": job.trigger_slot,
            "compute_start_slot": job.compute_start_slot,
            "ready_slot": job.ready_slot,
            "runtime_sec": job.runtime_sec,
            "runtime_slots": job.runtime_slots,
            "slot_sec": self.slot_sec,
            "controller_wait_slots": job.controller_wait_slots,
            "worker_id": job.worker_id,
            "q_link_sum_at_trigger": job.q_link_sum_at_trigger,
            "q_node_sum_at_trigger": job.q_node_sum_at_trigger,
            "mapping_cost": job.mapping_cost,
            "assign": repr(job.mapping.assign),
            "num_edge_paths": len(job.mapping.edge_paths),
            "completed_slot": "",
            "cold_buffer_released": 0,
        }
        self._oracle_job_records.append(record)
        self.logger.debug(
            "slot=%d | async launch | job=%d | commodity=%s | reason=%s | start=%d | ready=%d | runtime=%.6fs/%d slots | qsum=(%.3f, %.3f)",
            slot,
            job.oracle_job_id,
            cfg.commodity.name,
            reason,
            job.compute_start_slot,
            job.ready_slot,
            job.runtime_sec,
            job.runtime_slots,
            job.q_link_sum_at_trigger,
            job.q_node_sum_at_trigger,
        )
        return job

    def _mark_oracle_job_completed(self, job: _AsyncOracleJob, completed_slot: int, cold_released: int) -> None:
        for rec in reversed(self._oracle_job_records):
            if rec.get("oracle_job_id") == job.oracle_job_id:
                rec["completed_slot"] = int(completed_slot)
                rec["cold_buffer_released"] = int(cold_released)
                break

    def _inject_requests(
        self,
        slot: int,
        cfg: CommodityConfig,
        mapping: ValidMapping,
        requests: Sequence[_PendingRequest],
        source: str,
    ) -> int:
        if not requests:
            return 0
        dag = cfg.commodity.service_dag
        count = len(requests)
        self.virtual_queues.add_arrivals_of_mapping(dag, cfg.commodity, mapping, count)
        for req in requests:
            control_wait = float(max(0, int(slot) - int(req.born_slot)))
            self._control_wait_samples_injected.append(control_wait)
            self.physical_network.register_job(
                req.job_id,
                mapping,
                dag,
                cfg.commodity,
                born_time=req.born_slot,
                inject_time=slot,
            )
            self.physical_network.inject_one_unit(req.job_id)
        self.logger.debug(
            "slot=%d | inject | commodity=%s | source=%s | count=%d | mapping_cost=%.6f",
            slot,
            cfg.commodity.name,
            source,
            count,
            mapping.total_cost,
        )
        return count

    def _complete_ready_async_jobs(self, slot: int, cfg_by_key: Dict[Tuple[str, str], CommodityConfig]) -> int:
        released_total = 0
        while self._async_ready_heap and self._async_ready_heap[0][0] <= slot:
            _, _, key, job = heapq.heappop(self._async_ready_heap)
            cfg = cfg_by_key.get(key)
            if cfg is None:
                continue
            state = self._async_state.get(key)
            if state is None or state.pending_job is not job:
                continue
            state.pending_job = None
            state.current_mapping = job.mapping
            state.current_mapping_ready_slot = int(slot)
            state.current_mapping_snapshot_slot = int(job.trigger_slot)
            state.current_mapping_job_id = int(job.oracle_job_id)
            state.update_slots.append(int(slot))
            self._async_mapping_updates += 1

            cold_requests = list(state.cold_buffer)
            state.cold_buffer.clear()
            released = self._inject_requests(slot, cfg, job.mapping, cold_requests, source="cold_start_release")
            released_total += released
            self._mark_oracle_job_completed(job, completed_slot=slot, cold_released=released)
            self.logger.debug(
                "slot=%d | async ready | job=%d | commodity=%s | released=%d | mapping_cost=%.6f",
                slot,
                job.oracle_job_id,
                cfg.commodity.name,
                released,
                job.mapping.total_cost,
            )
        return released_total

    def _handle_async_arrivals(
        self,
        slot: int,
        cfg: CommodityConfig,
        arrivals: int,
        q_link_start: Mapping[Edge, float],
        q_node_start: Mapping[NodeId, float],
    ) -> int:
        if arrivals <= 0:
            return 0
        state = self._state_for(cfg)
        requests = [_PendingRequest(self._new_job_id(slot), int(slot)) for _ in range(arrivals)]
        if state.current_mapping is None:
            state.cold_buffer.extend(requests)
            self._async_cold_start_buffered_service_units += int(arrivals)
            if state.pending_job is None:
                self._launch_async_oracle_job(slot, cfg, q_link_start, q_node_start, reason="cold_start")
            self.logger.debug(
                "slot=%d | async cold-buffer | commodity=%s | arrivals=%d | buffer=%d",
                slot,
                cfg.commodity.name,
                arrivals,
                len(state.cold_buffer),
            )
            return 0

        # Existing mapping is ready.  The new arrivals enter immediately and
        # reuse the latest mapping even if a new mapping is being computed.
        injected = self._inject_requests(slot, cfg, state.current_mapping, requests, source="reuse_ready_mapping")
        self._async_reuse_service_units += int(arrivals)
        self._routing_cache_hits += int(arrivals)
        if state.current_mapping_snapshot_slot is not None:
            age = float(max(0, int(slot) - int(state.current_mapping_snapshot_slot)))
            self._mapping_age_samples.extend([age] * int(arrivals))
        if self.async_refresh_policy == "on_arrival" and state.pending_job is None:
            self._launch_async_oracle_job(slot, cfg, q_link_start, q_node_start, reason="arrival_refresh")
        return injected

    def _maybe_launch_continuous_async_refreshes(
        self,
        slot: int,
        cfg_by_key: Dict[Tuple[str, str], CommodityConfig],
    ) -> int:
        if self.async_refresh_policy != "continuous":
            return 0
        launched = 0
        q_link_now = self.virtual_queues.snapshot_link()
        q_node_now = self.virtual_queues.snapshot_node()
        for key, state in list(self._async_state.items()):
            if state.current_mapping is None:
                continue
            if state.pending_job is not None:
                continue
            cfg = cfg_by_key.get(key)
            if cfg is None:
                continue
            if self._launch_async_oracle_job(slot, cfg, q_link_now, q_node_now, reason="continuous_refresh") is not None:
                launched += 1
        return launched

    def _async_control_buffer_size(self) -> int:
        return sum(len(state.cold_buffer) for state in self._async_state.values())

    def _async_pending_oracle_jobs(self) -> int:
        return sum(1 for state in self._async_state.values() if state.pending_job is not None)

    def _mapping_age_stats_for_slot(self, slot: int) -> Tuple[float, float]:
        ages: List[float] = []
        for state in self._async_state.values():
            if state.current_mapping is not None and state.current_mapping_snapshot_slot is not None:
                ages.append(float(max(0, int(slot) - int(state.current_mapping_snapshot_slot))))
        if not ages:
            return 0.0, 0.0
        return float(sum(ages) / len(ages)), float(max(ages))

    def run(self) -> SimulationStats:
        stats = SimulationStats()
        started = time.perf_counter()
        label = self.run_label or "simulation"
        cfg_by_key = {self._cache_key(cfg): cfg for cfg in self.commodity_cfgs}
        self.logger.info(
            "Simulation start | run=%s | slots=%d | scheduler=%s | commodities=%d | seed=%d | activation=%s | fixed_k=%d | arrival_mode=%s | routing_mode=%s | slot_sec=%.6g | oracle_workers=%d | async_refresh_policy=%s",
            label,
            self.total_slots,
            self.scheduler,
            len(self.commodity_cfgs),
            self.seed,
            self.activation_policy.__class__.__name__,
            self.fixed_k,
            self.arrival_mode,
            self.routing_mode,
            self.slot_sec,
            self.oracle_workers,
            self.async_refresh_policy,
        )
        self.logger.debug("Network summary: %s", self.network.summary())

        for t in range(self.total_slots):
            self.physical_network.set_time(t)
            q_link_start = self.virtual_queues.snapshot_link()
            q_node_start = self.virtual_queues.snapshot_node()
            if self.routing_mode == "fixed_k":
                self._refresh_fixed_k_frame_if_needed(t, q_link_start, q_node_start)
            else:
                self._complete_ready_async_jobs(t, cfg_by_key)

            slot_arrivals = 0
            slot_injected_from_arrivals = 0

            # Arrivals + routing. All synchronous Fixed-K commodities in the
            # same slot observe the same slot-start virtual queues, consistent
            # with the original DCNC-DAG rule.  In async mode, only packets that
            # have a ready mapping are injected; cold-start packets remain in a
            # control-plane buffer until the first mapping is ready.
            for cfg in self.commodity_cfgs:
                dag = cfg.commodity.service_dag
                arrivals = self._sample_arrivals(cfg.arrival_rate)
                if arrivals <= 0:
                    continue
                slot_arrivals += arrivals
                self._generated_service_units += int(arrivals)
                self.logger.debug(
                    "slot=%d | commodity=%s | arrivals=%d | solver=%s",
                    t,
                    cfg.commodity.name,
                    arrivals,
                    cfg.solver.__class__.__name__,
                )
                if self.routing_mode == "fixed_k":
                    mapping = self._routing_mapping_for_slot(t, cfg, q_link_start, q_node_start)
                    self.logger.debug(
                        "slot=%d | commodity=%s | mapping_cost=%.6f | assign=%s",
                        t,
                        cfg.commodity.name,
                        mapping.total_cost,
                        mapping.assign,
                    )
                    self.virtual_queues.add_arrivals_of_mapping(dag, cfg.commodity, mapping, arrivals)
                    reqs = [_PendingRequest(self._new_job_id(t), t) for _ in range(arrivals)]
                    for req in reqs:
                        self.physical_network.register_job(req.job_id, mapping, dag, cfg.commodity, born_time=t, inject_time=t)
                        self.physical_network.inject_one_unit(req.job_id)
                        self._control_wait_samples_injected.append(0.0)
                    slot_injected_from_arrivals += arrivals
                else:
                    slot_injected_from_arrivals += self._handle_async_arrivals(t, cfg, arrivals, q_link_start, q_node_start)

            if self.routing_mode == "async_refresh":
                self._maybe_launch_continuous_async_refreshes(t, cfg_by_key)

            # Interference-aware link activation uses the same slot-start virtual
            # backlogs q_link_start and the current ON/OFF link state.  To avoid
            # pathological starvation when multiple schedules have the same
            # virtual weight, break ties very slightly toward edges that already
            # carry physical packets. This does not change decisions whenever the
            # virtual weights differ.
            edge_backlog_loads = self.physical_network.edge_backlog_loads()
            activation_q_link = {
                e: float(q_link_start.get(e, 0.0)) + self.activation_tie_break_eps * float(edge_backlog_loads.get(e, 0.0))
                for e in self.network.edges_all()
            }
            active_edges = self.activation_policy.select_active_edges(
                self.network,
                activation_q_link,
                self.physical_network.current_link_capacities,
            )
            self.physical_network.set_activated_edges(active_edges)

            # Physical system
            self.physical_network.serve_one_slot()
            # Virtual system: use the *actual activated* service.
            self.virtual_queues.serve_one_slot(
                link_service=self.physical_network.effective_link_service_map(),
            )

            # Stats
            vq_link = self.virtual_queues.total_link_backlog()
            vq_node = self.virtual_queues.total_node_backlog()
            phys_backlog = self.physical_network.total_backlog()
            stats.vq_link_sum_series.append(vq_link)
            stats.vq_node_sum_series.append(vq_node)
            stats.physical_backlog_series.append(phys_backlog)
            stats.activated_edge_count_series.append(self.physical_network.active_edge_count())
            control_buffer_size = self._async_control_buffer_size()
            age_avg, age_max = self._mapping_age_stats_for_slot(t)
            stats.control_buffer_sum_series.append(control_buffer_size)
            stats.mapping_age_avg_series.append(age_avg)
            stats.mapping_age_max_series.append(age_max)
            if self.record_timeseries:
                self._timeseries_records.append(
                    {
                        "slot": t,
                        "slot_arrivals": slot_arrivals,
                        "slot_injected_from_arrivals": slot_injected_from_arrivals,
                        "control_buffer_service_units": control_buffer_size,
                        "pending_oracle_jobs": self._async_pending_oracle_jobs(),
                        "active_edges": self.physical_network.active_edge_count(),
                        "delivered_packets": self.physical_network.delivered_packets,
                        "pending_packets": self.physical_network.pending_packets,
                        "completed_service_units": self.physical_network.completed_service_units,
                        "physical_backlog": phys_backlog,
                        "vq_link_sum": vq_link,
                        "vq_node_sum": vq_node,
                        "mapping_age_avg_slots": age_avg,
                        "mapping_age_max_slots": age_max,
                        "routing_oracle_calls_so_far": self._routing_oracle_calls,
                        "routing_oracle_wall_time_sec_so_far": self._routing_oracle_wall_time_sec,
                    }
                )
            self.logger.debug(
                "slot=%d | arrivals=%d | active_edges=%d | delivered=%d | pending=%d | phys_backlog=%d | vq_link=%.4f | vq_node=%.4f | ctrl_buffer=%d | map_age_avg=%.3f",
                t,
                slot_arrivals,
                self.physical_network.active_edge_count(),
                self.physical_network.delivered_packets,
                self.physical_network.pending_packets,
                phys_backlog,
                vq_link,
                vq_node,
                control_buffer_size,
                age_avg,
            )
            if t == 0 or (t + 1) % int(self.progress_every) == 0 or t == self.total_slots - 1:
                self.logger.info(
                    "Progress | run=%s | slot=%d/%d | arrivals=%d | active_edges=%d | delivered=%d | pending=%d | phys_backlog=%d | vq_link=%.4f | vq_node=%.4f | ctrl_buffer=%d | oracle_calls=%d",
                    label,
                    t + 1,
                    self.total_slots,
                    slot_arrivals,
                    self.physical_network.active_edge_count(),
                    self.physical_network.delivered_packets,
                    self.physical_network.pending_packets,
                    phys_backlog,
                    vq_link,
                    vq_node,
                    control_buffer_size,
                    self._routing_oracle_calls,
                )

        # Complete only jobs that have actually arrived in the simulated horizon.
        # Pending oracle jobs and control-buffered service units remain pending;
        # they are visible in the final statistics and time series.
        stats.delivered_packets = self.physical_network.delivered_packets
        stats.pending_packets = self.physical_network.pending_packets
        stats.total_packets = self.physical_network.total_packets
        stats.avg_delay_completed = self.physical_network.average_delay_completed()
        stats.avg_delay_with_penalty = self.physical_network.average_delay_with_penalty()
        stats.completed_service_units = self.physical_network.completed_service_units
        # Count all generated service units, including cold-start requests that
        # are still waiting in the control-plane buffer and have not yet been
        # registered in the physical network.
        control_buffer_final = self._async_control_buffer_size()
        stats.total_service_units = int(self._generated_service_units)
        stats.pending_service_units = int(self._generated_service_units - self.physical_network.completed_service_units)
        stats.avg_service_delay_completed = self.physical_network.average_service_delay_completed()
        if stats.total_service_units > 0:
            stats.avg_service_delay_with_penalty = (
                self.physical_network.service_delay_sum_completed
                + self.physical_network.unfinished_penalty * stats.pending_service_units
            ) / float(stats.total_service_units)
        stats.avg_packet_control_wait_completed = self.physical_network.average_packet_control_wait_completed()
        stats.avg_packet_network_delay_completed = self.physical_network.average_packet_network_delay_completed()
        stats.avg_service_control_wait_completed = self.physical_network.average_service_control_wait_completed()
        stats.avg_service_network_delay_completed = self.physical_network.average_service_network_delay_completed()
        stats.routing_oracle_calls = self._routing_oracle_calls
        stats.routing_cache_hits = self._routing_cache_hits
        stats.routing_oracle_wall_time_sec = self._routing_oracle_wall_time_sec
        stats.routing_oracle_runtime_samples_sec = list(self._routing_oracle_runtime_samples_sec)
        stats.async_mapping_updates = self._async_mapping_updates
        stats.async_refresh_triggers = self._async_refresh_triggers
        stats.async_reuse_service_units = self._async_reuse_service_units
        stats.async_cold_start_buffered_service_units = self._async_cold_start_buffered_service_units
        stats.async_control_wait_sum_slots_injected = float(sum(self._control_wait_samples_injected))
        if self._control_wait_samples_injected:
            waits = np.asarray(self._control_wait_samples_injected, dtype=float)
            stats.async_control_wait_avg_slots_injected = float(np.mean(waits))
            stats.async_control_wait_p95_slots_injected = float(np.percentile(waits, 95))
            stats.async_control_wait_max_slots_injected = float(np.max(waits))
        update_intervals: List[int] = []
        for state in self._async_state.values():
            if len(state.update_slots) >= 2:
                update_intervals.extend([b - a for a, b in zip(state.update_slots[:-1], state.update_slots[1:])])
        if update_intervals:
            stats.async_effective_update_interval_avg_slots = float(np.mean(update_intervals))
        if self._mapping_age_samples:
            ages = np.asarray(self._mapping_age_samples, dtype=float)
            stats.async_mapping_age_avg_slots = float(np.mean(ages))
            stats.async_mapping_age_max_slots = float(np.max(ages))
        elif stats.mapping_age_avg_series:
            stats.async_mapping_age_avg_slots = float(np.mean(stats.mapping_age_avg_series))
            stats.async_mapping_age_max_slots = float(max(stats.mapping_age_max_series))
        total_slot_sec = max(1e-12, float(self.total_slots) * self.slot_sec * float(self.oracle_workers))
        stats.async_controller_utilization = float(self._routing_oracle_wall_time_sec / total_slot_sec)
        stats.async_controller_queue_wait_sum_slots = self._async_controller_queue_wait_sum_slots
        stats.oracle_job_records = list(self._oracle_job_records)
        stats.timeseries_records = list(self._timeseries_records)
        elapsed = time.perf_counter() - started
        stats.simulation_wall_time_sec = elapsed
        self.logger.info(
            "Simulation done | run=%s | elapsed=%.3fs | delivered=%d | pending=%d | completed_service=%d | pending_service=%d | avg_delay=%.6f | avg_delay_penalty=%.6f | service_delay=%.6f | service_ctrl_wait=%.6f | service_network_delay=%.6f | oracle_calls=%d | oracle_time=%.6fs | cache_hits=%d | ctrl_buffer_final=%d",
            label,
            elapsed,
            stats.delivered_packets,
            stats.pending_packets,
            stats.completed_service_units,
            stats.pending_service_units,
            stats.avg_delay_completed,
            stats.avg_delay_with_penalty,
            stats.avg_service_delay_completed,
            stats.avg_service_control_wait_completed,
            stats.avg_service_network_delay_completed,
            stats.routing_oracle_calls,
            stats.routing_oracle_wall_time_sec,
            stats.routing_cache_hits,
            control_buffer_final,
        )
        return stats
