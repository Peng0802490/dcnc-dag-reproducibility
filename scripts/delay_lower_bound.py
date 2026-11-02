"""Finite-horizon request-delay lower bounds from complete requests and ages.

The denominator includes every arrival, including unfinished requests. These
are bounds on the realized requests' eventual mean delay, not on an optimal
policy or on steady-state delay. Never substitute a completed-only mean.
"""
from collections import defaultdict
import csv
import math
from pathlib import Path
import statistics

KEYS = ('kind', 'scenario', 'policy', 'solver', 'F', 'arrival_rate', 'horizon')


def run_lower_bound(job, record):
    stats = record.get('stats', {})
    audit = record.get('audit', {})
    required = ('completed_request_delay_sum', 'pending_registered_request_age_sum')
    if not all(k in audit for k in required):
        raise ValueError('Missing request-delay lower-bound audit sums; use the observed campaign runner (without --native).')
    params = job['params']
    def count(name):
        value = stats[name]
        if isinstance(value, bool) or not math.isfinite(value) or int(value) != value or value < 0:
            raise ValueError('Invalid request count: ' + name)
        return int(value)
    n = count('total_service_units')
    nc = count('completed_service_units')
    nu = count('pending_service_units')
    horizon = int(params['slots'])
    completed, ages = (float(audit[k]) for k in required)
    if horizon <= 0 or n != nc + nu:
        raise ValueError('Invalid horizon or request conservation')
    if not all(math.isfinite(x) and x >= 0 for x in (completed, ages)):
        raise ValueError('Invalid delay/age sum')
    if nc:
        mean_completed = stats['avg_service_delay_completed']
        if not math.isclose(completed, nc * mean_completed, rel_tol=1e-12, abs_tol=1e-6):
            raise ValueError('Completed delay sum disagrees with request statistics')
    elif completed != 0:
        raise ValueError('Nonzero delay sum with no completed requests')
    if completed > nc * horizon or not nu <= ages <= nu * horizon:
        raise ValueError('Delay/age sum outside the recorded horizon')
    for name in ('async_reuse_service_units', 'async_cold_start_buffered_service_units',
                 'async_control_wait_sum_slots_injected'):
        if stats.get(name, 0) != 0:
            raise ValueError('Asynchronous requests require additional accounting: ' + name)
    result = record['result']
    return dict(run_id=job['id'], kind=job['kind'],
                scenario=params.get('case', params.get('workflow', params.get('model', 'capacity'))),
                policy=params.get('policy', result.get('policy')),
                solver=params.get('solver', params.get('dcnc_solver', '')), F=params.get('fixed_k', 1),
                arrival_rate=params.get('rate', params.get('arrival_rate', params.get('total_arrival_rate'))),
                seed=params['seed'], horizon=horizon, arrived_requests=n, completed_requests=nc,
                unfinished_requests=nu, completed_delay_sum_slots=completed, unfinished_age_sum_slots=ages,
                mean_request_delay_lower_bound=(completed + ages) / n if n else None,
                mean_completed_request_delay=stats['avg_service_delay_completed'] if nc else None,
                completion_ratio=nc / n if n else None,
                source_result_path='data/runs/' + job['id'] + '/result.json')


def summarize_lower_bounds(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in KEYS)].append(row)
    summaries = []
    for key, group in sorted(groups.items(), key=lambda item: str(item[0])):
        if len({r['seed'] for r in group}) != len(group):
            raise ValueError('Duplicate seed in lower-bound group: ' + str(key))
        values = [r['mean_request_delay_lower_bound'] for r in group]
        valid = all(v is not None for v in values)
        ratios = [r['completion_ratio'] for r in group]
        summary = dict(zip(KEYS, key))
        summary.update(seeds=len(group),
                       mean_request_delay_lower_bound=statistics.mean(values) if valid else None,
                       lower_bound_se=statistics.stdev(values) / math.sqrt(len(values)) if valid and len(values) > 1 else None,
                       mean_completion_ratio=statistics.mean(ratios) if all(r is not None for r in ratios) else None,
                       all_seeds_complete=all(r['unfinished_requests'] == 0 for r in group))
        summaries.append(summary)
    return summaries


def export_lower_bounds(rows, destination):
    if not rows:
        return
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name, records in [('runs.csv', rows), ('summary.csv', summarize_lower_bounds(rows))]:
        with (destination / name).open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
