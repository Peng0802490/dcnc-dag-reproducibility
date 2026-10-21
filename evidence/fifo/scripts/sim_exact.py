"""Independent minimal simulator for the two-node re-entrant-line instance.

Written from the paper specification only (Section VII-F of `TMC (2).tex`, and
Section 1 of `FIFO_sawtooth_review_prompt.md`).  It shares no code with
`sim_links.py`; it exists to cross-validate that simulator (experiment E-7) and
to supply the instrumentation the audit needs.

Instance
--------
Two compute nodes ``u1`` (index 0) and ``v1`` (index 1), capacity ``mu`` each.
One six-stage chain ``A -> B -> C -> E -> F -> G`` placed ``A,G -> u1`` and
``B,C,E,F -> v1``.  Computation workloads default to
``[0.01, 0.99, 0.01, 0.01, 0.01, 0.99]``.  Cross-node hops (A->B on u1->v1 and
F->G on v1->u1) optionally traverse a directed link of workload ``xi`` served at
rate ``mu_link``; same-node hops take the empty path.  Every hop is released at
the end of a slot and becomes visible at ``t+1``.

Two arithmetic modes
--------------------
``arith="int"``    every workload and capacity is scaled by ``SCALE=100`` so all
                   comparisons are exact integer arithmetic.  Service is
                   batched: all jobs queued at one stage carry the same
                   workload, so serving them one at a time and serving them as a
                   block are identical, and the block form is far faster.
``arith="float"``  reproduces the IEEE-754 scalar loop of ``sim_links.py``
                   (``if rem <= budget: budget -= rem``) job by job, so a
                   float-vs-float comparison isolates implementation
                   differences from arithmetic differences.

Random number streams (audit item A-8)
--------------------------------------
Three independent, purpose-named streams from ``SeedSequence(seed).spawn(3)``:
``arrival``, ``tiebreak``, ``spare``.  The arrival stream draws exactly one
uniform per slot regardless of ``lam``, so arrival paths are nested in ``lam``
(common random numbers, experiment E-1).
"""
from __future__ import annotations

import bisect
from array import array
from collections import deque

import numpy as np

SCALE = 100
STAGE_NODE = (0, 1, 1, 1, 1, 0)
STAGE_NAME = ("A", "B", "C", "E", "F", "G")
WORK_DEFAULT = (0.01, 0.99, 0.01, 0.01, 0.01, 0.99)
S = 6
COMPACT_AT = 1 << 16


def make_streams(seed):
    """Independent, purpose-named RNG streams (A-8)."""
    children = np.random.SeedSequence(seed).spawn(3)
    return {
        "arrival": np.random.default_rng(children[0]),
        "tiebreak": np.random.default_rng(children[1]),
        "spare": np.random.default_rng(children[2]),
    }


def arrival_indicators(T, lam, seed, process="bernoulli", legacy_stream=False):
    """Per-slot arrival counts as a uint8 array.

    ``process="bernoulli"``  u_t < lam, one uniform per slot from a
                             lam-independent stream -> nested in lam.
    ``process="periodic"``   Bresenham pacing: acc += lam, emit floor(acc).
    ``legacy_stream=True``   use ``default_rng(seed)`` directly, i.e. the exact
                             stream of ``sim_links.py``, for bit-exact
                             cross-validation of E-7.
    """
    if process == "periodic":
        acc = 0.0
        out = np.empty(T, dtype=np.uint8)
        for t in range(T):
            acc += lam
            k = int(acc)
            acc -= k
            out[t] = k
        return out
    if process != "bernoulli":
        raise ValueError("unknown arrival process: %r" % (process,))
    rng = np.random.default_rng(seed) if legacy_stream else make_streams(seed)["arrival"]
    out = np.empty(T, dtype=np.uint8)
    step = 1 << 20
    for lo in range(0, T, step):
        hi = min(lo + step, T)
        out[lo:hi] = (rng.random(hi - lo) < lam).astype(np.uint8)
    return out


class Node(object):
    """One compute node: a seq-ordered queue of waiting jobs per hosted stage.

    Jobs queued at one stage are interchangeable (identical workload), so a job
    is represented by its enqueue sequence number alone.  ``ids`` is populated
    only when a tie-break rule needs the original request identity, because at
    high offered rates the unstable queues hold millions of jobs.
    """

    __slots__ = ("stages", "seqs", "ids", "head", "rem", "count", "track_ids")

    def __init__(self, stages, track_ids=False):
        self.stages = tuple(stages)
        self.track_ids = track_ids
        self.seqs = dict((s, array("q")) for s in stages)
        self.ids = dict((s, array("q")) for s in stages) if track_ids else None
        self.head = dict((s, 0) for s in stages)
        self.rem = dict((s, 0) for s in stages)
        self.count = dict((s, 0) for s in stages)

    def push(self, s, seq, jid, full_work):
        if self.count[s] == 0:
            self.rem[s] = full_work
        self.seqs[s].append(seq)
        if self.track_ids:
            self.ids[s].append(jid)
        self.count[s] += 1

    def nonempty(self):
        for s in self.stages:
            if self.count[s]:
                return True
        return False

    def compact(self, s):
        h = self.head[s]
        if h >= COMPACT_AT and h * 2 >= len(self.seqs[s]):
            del self.seqs[s][:h]
            if self.track_ids:
                del self.ids[s][:h]
            self.head[s] = 0


def simulate(lam,
             seed,
             policy="FIFO",
             T=2_000_000,
             M0=500,
             work=WORK_DEFAULT,
             mu=1.0,
             xi_link=0.1,
             mu_link=10.0,
             use_links=True,
             arith="int",
             arrivals="bernoulli",
             tiebreak="completion",
             legacy_stream=False,
             n_segments=10,
             trace_window=None,
             sample_every=0,
             scale=SCALE,
             check_partials=False,
             nonpreempt=False):
    """Run one sample path.  Returns scalars, invariants and optional traces."""
    if arith not in ("int", "float"):
        raise ValueError("arith must be 'int' or 'float'")
    is_int = arith == "int"
    if is_int:
        w = [int(round(x * scale)) for x in work]
        cap = int(round(mu * scale))
        xi = int(round(xi_link * scale))
        cap_link = int(round(mu_link * scale))
        for x, wi in zip(work, w):
            if abs(x * scale - wi) > 1e-9:
                raise ValueError("workload %r is not exact at scale %d" % (x, scale))
        eps = 0
    else:
        w = [float(x) for x in work]
        cap = float(mu)
        xi = float(xi_link)
        cap_link = float(mu_link)
        eps = 1e-12

    # "GLOBAL_FCFS" is not a policy of the paper; it exists so audit item A-5 can
    # show that ordering by request birth time is a different discipline from
    # ordering by arrival at the node.
    is_fifo = policy in ("FIFO", "GLOBAL_FCFS")
    use_id_key = policy == "GLOBAL_FCFS"
    track_ids = tiebreak == "id_asc" or use_id_key
    nodes = (Node([s for s in range(S) if STAGE_NODE[s] == 0], track_ids),
             Node([s for s in range(S) if STAGE_NODE[s] == 1], track_ids))

    arr = arrival_indicators(T, lam, seed, arrivals, legacy_stream=legacy_stream)
    tb_rng = make_streams(seed)["tiebreak"]

    seq = 0
    jid = 0
    for _ in range(M0):                      # A-10: identical preload at stage A
        nodes[0].push(0, seq, jid, w[0])
        seq += 1
        jid += 1
    stage_count = [0] * S
    stage_count[0] = M0

    link_q = {(0, 1): deque(), (1, 0): deque()}
    link_rem = {(0, 1): xi, (1, 0): xi}
    link_served = {(0, 1): 0, (1, 0): 0}
    link_qmax = {(0, 1): 0, (1, 0): 0}

    transit_node = []          # (stage, jid) entering a node queue at t+1
    transit_link = []          # (src, dst, stage, jid) entering a link at t+1

    completed = 0
    arrivals_total = 0
    departures = [0] * S       # jobs that finished each stage (A-2 / A-4)
    served = [0, 0]            # S_r : workload actually served
    idle_empty = [0, 0]        # I_r : leftover budget with an empty node queue
    idle_nonempty = [0, 0]     # L_r : leftover budget with work still waiting
    slots_starved = [0, 0]     # slots where the node did nothing at all
    multi_partial_slots = [0, 0]   # slot ends carrying >1 partially served job
    max_partial = [0, 0]

    seg_len = max(1, T // n_segments)
    seg_completed = []
    seg_arrivals = []          # cumulative A_cum at each segment boundary
    seg_next = seg_len

    if trace_window is not None:
        tw0, tw1 = trace_window
        n_tr = tw1 - tw0
        tr_stage = np.zeros((n_tr, S), dtype=np.int32)
        tr_used = np.zeros((n_tr, 2), dtype=np.int32)
    else:
        tw0, tw1 = -1, -1
        tr_stage = tr_used = None

    if sample_every:
        n_smp = T // sample_every + 1
        smp_stage = np.zeros((n_smp, S), dtype=np.int32)
        smp_completed = np.zeros(n_smp, dtype=np.int64)
        smp_arrivals = np.zeros(n_smp, dtype=np.int64)
        smp_served = np.zeros((n_smp, 2), dtype=np.int64)
        smp_i = 0
    else:
        smp_stage = smp_completed = smp_served = smp_arrivals = None

    for t in range(T):
        # ---------------- slot start: releases, then arrivals ----------------
        if transit_node:
            if tiebreak == "id_asc":
                transit_node.sort(key=lambda j: j[1])
            elif tiebreak == "stage_asc":
                transit_node.sort(key=lambda j: j[0])
            elif tiebreak == "stage_desc":
                transit_node.sort(key=lambda j: -j[0])
            elif tiebreak == "random":
                order = tb_rng.permutation(len(transit_node))
                transit_node = [transit_node[i] for i in order]
            for st, ji in transit_node:
                nodes[STAGE_NODE[st]].push(st, seq, ji, w[st])
                seq += 1
            transit_node = []
        if transit_link:
            for src, dst, st, ji in transit_link:
                key = (src, dst)
                if not link_q[key]:
                    link_rem[key] = xi
                link_q[key].append((st, ji))
                seq += 1                       # keep the counter aligned
            transit_link = []

        k = int(arr[t])
        if k:
            arrivals_total += k
            nd = nodes[0]
            for _ in range(k):
                nd.push(0, seq, jid, w[0])
                seq += 1
                jid += 1
            stage_count[0] += k

        # ---------------------------- node service ---------------------------
        for n in (0, 1):
            nd = nodes[n]
            budget = cap
            son = nd.stages
            key_of = nd.ids if use_id_key else nd.seqs
            while budget > eps:
                chosen = -1
                second = None
                forced = False
                if nonpreempt:
                    # finish any job already under service before starting another
                    for s in son:
                        if nd.count[s] and nd.rem[s] != w[s]:
                            chosen = s
                            forced = True
                            break
                if forced:
                    pass
                elif is_fifo:
                    best = None
                    for s in son:
                        if nd.count[s]:
                            hs = key_of[s][nd.head[s]]
                            if best is None or hs < best:
                                if best is not None and (second is None or best < second):
                                    second = best
                                best = hs
                                chosen = s
                            elif second is None or hs < second:
                                second = hs
                else:
                    for s in son:              # ascending stage index = hop grade
                        if nd.count[s]:
                            chosen = s
                            break
                if chosen < 0:
                    break

                ws = w[chosen]
                r = nd.rem[chosen]
                if r > budget:                 # cannot even finish the head job
                    nd.rem[chosen] = r - budget
                    served[n] += budget
                    budget -= budget
                    break
                budget -= r
                served[n] += r

                h = nd.head[chosen]
                if forced:
                    avail = 0          # resume only the job already under service
                elif is_fifo and second is not None:
                    lst = key_of[chosen]
                    avail = bisect.bisect_left(lst, second, h, h + nd.count[chosen]) - h - 1
                else:
                    avail = nd.count[chosen] - 1
                if is_int:
                    nfull = budget // ws
                    kfull = nfull if nfull < avail else avail
                    if kfull < 0:
                        kfull = 0
                    budget -= kfull * ws
                    served[n] += kfull * ws
                    ndone = 1 + kfull
                else:
                    ndone = 1
                    while ndone <= avail and ws <= budget:
                        budget -= ws
                        served[n] += ws
                        ndone += 1

                departures[chosen] += ndone
                nxt = chosen + 1
                if nxt >= S:
                    completed += ndone
                else:
                    ids = nd.ids[chosen] if track_ids else None
                    dn = STAGE_NODE[nxt]
                    if use_links and dn != n:
                        if track_ids:
                            for i in range(h, h + ndone):
                                transit_link.append((n, dn, nxt, ids[i]))
                        else:
                            transit_link.extend([(n, dn, nxt, 0)] * ndone)
                    else:
                        if track_ids:
                            for i in range(h, h + ndone):
                                transit_node.append((nxt, ids[i]))
                        else:
                            transit_node.extend([(nxt, 0)] * ndone)
                    stage_count[nxt] += ndone
                stage_count[chosen] -= ndone
                nd.head[chosen] = h + ndone
                nd.count[chosen] -= ndone
                nd.rem[chosen] = ws
                nd.compact(chosen)

            if check_partials:
                np_partial = 0
                for s in son:
                    if nd.count[s] and nd.rem[s] != w[s]:
                        np_partial += 1
                if np_partial > 1:
                    multi_partial_slots[n] += 1
                if np_partial > max_partial[n]:
                    max_partial[n] = np_partial

            if budget > 0:                     # A-3 / E-5 capacity decomposition
                if nd.nonempty():
                    idle_nonempty[n] += budget
                else:
                    idle_empty[n] += budget
                    if budget == cap:
                        slots_starved[n] += 1

            if tw0 <= t < tw1:
                tr_used[t - tw0, n] = cap - budget

        # ------------------------------ link service -------------------------
        if use_links:
            for key in ((0, 1), (1, 0)):
                lq = link_q[key]
                if len(lq) > link_qmax[key]:
                    link_qmax[key] = len(lq)
                if not lq:
                    continue
                budget = cap_link
                r = link_rem[key]
                if r > budget:
                    link_rem[key] = r - budget
                    link_served[key] += budget
                    continue
                budget -= r
                link_served[key] += r
                st, ji = lq.popleft()
                transit_node.append((st, ji))
                if is_int:
                    nfull = budget // xi
                    kfull = nfull if nfull < len(lq) else len(lq)
                    for _ in range(kfull):
                        transit_node.append(lq.popleft())
                    budget -= kfull * xi
                    link_served[key] += kfull * xi
                else:
                    while lq and xi <= budget:
                        budget -= xi
                        link_served[key] += xi
                        transit_node.append(lq.popleft())
                link_rem[key] = xi

        # -------------------------------- record -----------------------------
        if tw0 <= t < tw1:
            tr_stage[t - tw0] = stage_count
        if sample_every and t % sample_every == 0:
            smp_stage[smp_i] = stage_count
            smp_completed[smp_i] = completed
            smp_arrivals[smp_i] = arrivals_total
            smp_served[smp_i, 0] = served[0]
            smp_served[smp_i, 1] = served[1]
            smp_i += 1
        if t + 1 >= seg_next:
            seg_completed.append(completed)
            seg_arrivals.append(arrivals_total)
            seg_next += seg_len

    in_system = sum(stage_count)
    conservation_ok = (in_system + completed) == (M0 + arrivals_total)

    # A-2 / A-4: reconcile served workload against completed stage-services plus
    # the work already invested in the at-most-one partially served job per stage.
    recon = []
    for n in (0, 1):
        expect = 0
        for s in nodes[n].stages:
            expect += departures[s] * w[s]
            if nodes[n].count[s]:
                expect += w[s] - nodes[n].rem[s]
        recon.append(served[n] - expect)

    denom = float(scale) if is_int else 1.0
    total_cap = float(cap) * T / denom
    out = {
        "lam": lam, "seed": seed, "policy": policy, "T": T, "M0": M0,
        "arith": arith, "arrivals": arrivals, "tiebreak": tiebreak,
        "use_links": use_links, "work": tuple(work),
        "arrivals_total": arrivals_total,
        "completed": completed,
        "final_backlog": in_system,
        "stage_count": tuple(stage_count),
        "completed_throughput": completed / float(T),
        "completion_ratio": completed / float(M0 + arrivals_total) if (M0 + arrivals_total) else 1.0,
        "net_backlog_growth": (in_system - M0) / float(T),
        "served_u1": served[0] / denom, "served_v1": served[1] / denom,
        "idle_empty_u1": idle_empty[0] / denom, "idle_empty_v1": idle_empty[1] / denom,
        "idle_nonempty_u1": idle_nonempty[0] / denom, "idle_nonempty_v1": idle_nonempty[1] / denom,
        "starved_slots_u1": slots_starved[0], "starved_slots_v1": slots_starved[1],
        "capacity_total_per_node": total_cap,
        "budget_identity_u1": (served[0] + idle_empty[0] + idle_nonempty[0]) / denom,
        "budget_identity_v1": (served[1] + idle_empty[1] + idle_nonempty[1]) / denom,
        "link_util_01": link_served[(0, 1)] / denom / (float(cap_link) * T / denom) if use_links else 0.0,
        "link_util_10": link_served[(1, 0)] / denom / (float(cap_link) * T / denom) if use_links else 0.0,
        "link_qmax_01": link_qmax[(0, 1)], "link_qmax_10": link_qmax[(1, 0)],
        "link_qfinal_01": len(link_q[(0, 1)]), "link_qfinal_10": len(link_q[(1, 0)]),
        "conservation_ok": conservation_ok,
        "multi_partial_slots_u1": multi_partial_slots[0],
        "multi_partial_slots_v1": multi_partial_slots[1],
        "max_partial_jobs_u1": max_partial[0],
        "max_partial_jobs_v1": max_partial[1],
        "departures": tuple(departures),
        "service_reconciliation_u1": recon[0] / denom,
        "service_reconciliation_v1": recon[1] / denom,
        "segments": seg_completed,
        "segment_arrivals": seg_arrivals,
        "seg_len": seg_len,
    }
    if seg_completed and len(seg_completed) >= 10:
        out["terminal_rate"] = (seg_completed[-1] - seg_completed[-3]) / float(2 * seg_len)
    else:
        out["terminal_rate"] = out["completed_throughput"]
    if trace_window is not None:
        out["trace_stage"] = tr_stage
        out["trace_used"] = tr_used
        out["trace_t0"] = tw0
    if sample_every:
        out["sample_every"] = sample_every
        out["sample_stage"] = smp_stage[:smp_i]
        out["sample_completed"] = smp_completed[:smp_i]
        out["sample_arrivals"] = smp_arrivals[:smp_i]
        out["sample_served"] = smp_served[:smp_i]
    return out
