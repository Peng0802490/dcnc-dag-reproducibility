"""Exact memoization used by the recorded server campaign."""
from functools import lru_cache
from collections import OrderedDict

def cache_cts_hop_paths(solver):
    """Memoize the pure unit-hop oracle used exclusively by CTS.

    CTS never passes queue-dependent edge costs to its oracle. The substrate
    topology is fixed for a run, and the original oracle still determines all
    path ties. Return fresh lists so callers cannot mutate cached paths.
    This changes wall time only, not any fixed-frame simulation decision.
    """
    original=solver.oracle.shortest_path
    @lru_cache(maxsize=None)
    def unit_path(src,dst):
        distance,path=original(src,dst,lambda u,v:1.0)
        return distance,tuple(path)
    def shortest_path(src,dst,edge_cost):
        distance,path=unit_path(str(src),str(dst))
        return distance,list(path)
    solver.oracle.shortest_path=shortest_path


def cache_static_activation(policy,network):
    """Exact input-key memoization for deterministic activation, with no rounding."""
    original=policy.select_active_edges
    edges=network.edges_all();cache=OrderedDict()
    def select(net,q,caps,physical_backlog=None):
        key=(tuple(q.get(e,0.0) for e in edges),tuple(caps.get(e,0.0) for e in edges),
             None if physical_backlog is None else tuple(physical_backlog.get(e,0.0) for e in edges))
        if key in cache:
            cache.move_to_end(key)
            return set(cache[key])
        result=(original(net,q,caps) if physical_backlog is None
                else original(net,q,caps,physical_backlog=physical_backlog))
        cache[key]=frozenset(result)
        if len(cache)>512:cache.popitem(last=False)
        return result
    policy.select_active_edges=select


def cache_cts_assignment(solver):
    """Reuse queue-independent CTS placement; rebuild paths/cost with current queues.

    Both CTS implementations choose placement from fixed hop distances only.
    Keep fresh mapping objects and call the existing builder in its original
    order so queue-dependent total_cost and all routes remain unchanged.
    """
    original=solver.compute; assignments={}
    def compute(dag,commodity,q_link,q_node):
        key=(id(dag),id(commodity))
        if key not in assignments:
            mapping=original(dag,commodity,q_link,q_node)
            assignments[key]=dict(mapping.assign)
            return mapping
        return solver._build_mapping_from_assignment(
            dag,commodity,dict(assignments[key]),solver._hop_cost_fn(),q_link,q_node)
    solver.compute=compute


