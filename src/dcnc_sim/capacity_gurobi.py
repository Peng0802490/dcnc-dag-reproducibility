from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence, Tuple

from .capacity import MappingResourceUsage, enumerate_iid_onoff_state_activations_small, usage_of_mapping
from .interference import BaseActivationPolicy
from .mapping import ValidMapping
from .models import Commodity, DistributedComputingNetwork, Edge, NodeId, ServiceDAG


@dataclass
class CapacityLPResult:
    objective: float
    solver: str
    status: str
    num_mappings: int
    mapping_rates: Dict[int, float] = field(default_factory=dict)
    link_load: Dict[Edge, float] = field(default_factory=dict)
    node_load: Dict[NodeId, float] = field(default_factory=dict)
    avg_link_service: Dict[Edge, float] = field(default_factory=dict)


def solve_single_commodity_capacity_gurobi(
    network: DistributedComputingNetwork,
    dag: ServiceDAG,
    commodity: Commodity,
    mappings: Sequence[ValidMapping],
    dynamic_edge_p_on: Mapping[Edge, float],
    activation_policy: BaseActivationPolicy,
    time_limit: Optional[float] = None,
    output_flag: bool = False,
) -> CapacityLPResult:
    """Solve the single-commodity service-rate capacity LP with Gurobi.

    Variables are valid-mapping flow rates f_k and state-action time shares
    y_{sigma,a}=p_sigma alpha_{sigma,a}.  The objective maximizes sum_k f_k.
    This implements the valid-mapping capacity-region characterization used in
    the paper for small synthetic instances where all mappings can be enumerated.
    """

    if not mappings:
        raise ValueError("no valid mappings provided")

    try:
        import gurobipy as gp
        from gurobipy import GRB
    except Exception as exc:  # pragma: no cover - depends on server license/env
        raise RuntimeError(
            "gurobipy is not available. Install/configure Gurobi first, or run the validation script with --lp-solver scipy for a fallback check."
        ) from exc

    usages = [usage_of_mapping(network, dag, commodity, m) for m in mappings]
    states = enumerate_iid_onoff_state_activations_small(network, dynamic_edge_p_on, activation_policy)

    model = gp.Model("dcnc_single_commodity_capacity")
    model.Params.OutputFlag = 1 if output_flag else 0
    if time_limit is not None and float(time_limit) > 0:
        model.Params.TimeLimit = float(time_limit)

    f = model.addVars(len(mappings), lb=0.0, name="f")
    y = {}
    for si, state in enumerate(states):
        for ai, _activation in enumerate(state.activation_sets):
            y[(si, ai)] = model.addVar(lb=0.0, name=f"y[{si},{ai}]")

    model.setObjective(gp.quicksum(f[k] for k in range(len(mappings))), GRB.MAXIMIZE)

    for edge in network.edges_all():
        load_expr = gp.quicksum(float(usages[k].link_usage[edge]) * f[k] for k in range(len(mappings)))
        service_expr = gp.quicksum(
            float(state.activation_sets[ai].get(edge, 0.0)) * y[(si, ai)]
            for si, state in enumerate(states)
            for ai in range(len(state.activation_sets))
        )
        model.addConstr(load_expr <= service_expr, name=f"link[{edge[0]}->{edge[1]}]")

    for node in network.nodes_all():
        load_expr = gp.quicksum(float(usages[k].node_usage[node]) * f[k] for k in range(len(mappings)))
        model.addConstr(load_expr <= float(network.node_capacity(node)), name=f"node[{node}]")

    for si, state in enumerate(states):
        model.addConstr(
            gp.quicksum(y[(si, ai)] for ai in range(len(state.activation_sets))) == float(state.probability),
            name=f"state[{si}]",
        )

    model.optimize()
    if model.Status not in {GRB.OPTIMAL, GRB.TIME_LIMIT}:
        raise RuntimeError(f"Gurobi capacity LP failed with status={model.Status}")
    if model.SolCount <= 0:
        raise RuntimeError(f"Gurobi capacity LP produced no incumbent solution; status={model.Status}")

    mapping_rates = {k: float(f[k].X) for k in range(len(mappings)) if float(f[k].X) > 1e-10}
    link_load = {edge: 0.0 for edge in network.edges_all()}
    node_load = {node: 0.0 for node in network.nodes_all()}
    for k, rate in mapping_rates.items():
        for edge in network.edges_all():
            link_load[edge] += rate * float(usages[k].link_usage[edge])
        for node in network.nodes_all():
            node_load[node] += rate * float(usages[k].node_usage[node])

    avg_link_service = {edge: 0.0 for edge in network.edges_all()}
    for si, state in enumerate(states):
        for ai, activation in enumerate(state.activation_sets):
            val = float(y[(si, ai)].X)
            if val <= 1e-12:
                continue
            for edge in network.edges_all():
                avg_link_service[edge] += val * float(activation.get(edge, 0.0))

    return CapacityLPResult(
        objective=float(model.ObjVal),
        solver="gurobi",
        status=str(model.Status),
        num_mappings=len(mappings),
        mapping_rates=mapping_rates,
        link_load=link_load,
        node_load=node_load,
        avg_link_service=avg_link_service,
    )


def solve_single_commodity_capacity_scipy(
    network: DistributedComputingNetwork,
    dag: ServiceDAG,
    commodity: Commodity,
    mappings: Sequence[ValidMapping],
    dynamic_edge_p_on: Mapping[Edge, float],
    activation_policy: BaseActivationPolicy,
) -> CapacityLPResult:
    """SciPy fallback with the same LP, used only for quick local smoke tests."""

    from .capacity import maximum_single_commodity_rate_iid_onoff_with_activation

    objective = maximum_single_commodity_rate_iid_onoff_with_activation(
        network=network,
        dag=dag,
        commodity=commodity,
        mappings=mappings,
        dynamic_edge_p_on=dynamic_edge_p_on,
        activation_policy=activation_policy,
    )
    usages = [usage_of_mapping(network, dag, commodity, m) for m in mappings]
    return CapacityLPResult(
        objective=float(objective),
        solver="scipy",
        status="optimal",
        num_mappings=len(mappings),
        mapping_rates={},
        link_load={edge: 0.0 for edge in network.edges_all()},
        node_load={node: 0.0 for node in network.nodes_all()},
        avg_link_service={},
    )
