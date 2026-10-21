# New Section 7.2 Validation Instance — Simulation Specification

This document fully specifies the **wireless mixed-mapping fork-join instance** that replaces
the two instances currently in Section 7.2 (the wireless fork-join whose optimum was met by a
single mapping, and the always-ON mixed-mapping check). The new instance is designed so that

1. it carries **wireless links with ON/OFF dynamics and primary interference** (so it exercises
   the max-weight activation, NTO scheduling, and synchronization machinery), **and**
2. its capacity is attained **only by a nontrivial mixture of two valid mappings** (so it
   exercises the queue-priced mapping decision — the point the old single-mapping-optimal
   instance could not make).

Run it, then fill the `TBD` cells in **Table 3** of the main text (`tab:throughput_boundary_validation`)
and confirm the numbers quoted in the prose of Sec. 7.2 and Sec. S5.2 of the supplement.

---

## 1. Instance definition

### 1.1 Service DAG (fork-join)

Functions `A, B, C, D` with dependencies

```
A → B,   A → C,   B → D,   C → D
```

`A` is the (single) source function, `D` the (single) sink function. Augmented edges add the
service source `S_A → A` and the service sink `D → D_out`.

| quantity | value |
|---|---|
| computation `r^A, r^B, r^D` | `0.1` each (light) |
| computation `r^C` | `1.0` (heavy — this is the function that is balanced) |
| `ξ` on `A→C` and `C→D` | `1.0` (heavy branch) |
| `ξ` on `A→B` and `B→D` | `0.2` (light branch) |
| source input `in(A)` = `ξ(S_A→A)` | `0.2` |
| sink output `out(D)` = `ξ(D→D_out)` | `0.2` |

All factors are rational, as the model requires.

### 1.2 Substrate network

Nodes: `s, u_A, u_B, u_C1, u_C2, u_D, d` (7 nodes).

Directed links, **in this fixed order** (used for all load vectors below):

| # | link | role | wireless? | capacity |
|---|---|---|---|---|
| 1 | `s → u_A` | carries `S_A→A` | always ON | 2 |
| 2 | `u_A → u_B` | carries `A→B` | always ON | 2 |
| 3 | `u_B → u_D` | carries `B→D` | always ON | 2 |
| 4 | `u_A → u_C1` | carries `A→C` for `m1` | **ON w.p. 0.85** | 2 |
| 5 | `u_C1 → u_D` | carries `C→D` for `m1` | **ON w.p. 0.85** | 2 |
| 6 | `u_A → u_C2` | carries `A→C` for `m2` | **ON w.p. 0.85** | 2 |
| 7 | `u_C2 → u_D` | carries `C→D` for `m2` | **ON w.p. 0.85** | 2 |
| 8 | `u_D → d` | carries `D→D_out` | always ON | 2 |

- The four `C`-branch links (4–7) are the wireless links. Each is **independently ON with
  probability 0.85 per slot, i.i.d.** across slots and across links. The other four links are
  always ON.
- **Interference: primary** (each node incident to at most one activated link per slot),
  exactly as in the four-topology experiments and Remark 1. So the activation step is a
  maximum-weight matching over the currently-ON links, as elsewhere.
- Bidirectional modeling is not needed here — all links are used in one direction only.

### 1.3 Computation capacities

| node | compute capacity |
|---|---|
| `u_C1` | **0.5** |
| `u_C2` | **0.5** |
| `u_A, u_B, u_D` | 5 (non-binding) |
| `s, d` | forwarding only (no computation) |

The `0.5` capacity at each of `u_C1, u_C2` is the crux: the heavy function `C` (`r^C = 1`) can be
run at only 1 request every 2 slots per node.

### 1.4 Placement / valid mappings

- `A @ u_A`, `B @ u_B`, `D @ u_D` are pinned.
- `C ∈ {u_C1, u_C2}` — the only degree of freedom.
- Source endpoint `S_A @ s`, sink endpoint `D_out @ d`.

This yields **exactly two valid mappings**:

- **`m1`: `C @ u_C1`** — routes `A→C` on `u_A→u_C1`, `C→D` on `u_C1→u_D`.
- **`m2`: `C @ u_C2`** — routes `A→C` on `u_A→u_C2`, `C→D` on `u_C2→u_D`.

Both mappings route the light branch identically (`u_A→u_B→u_D`) and the source/sink on
`s→u_A` / `u_D→d`.

### 1.5 Per-request load vectors (verify these in code)

Link order = the 8 links above. Node order = `(u_A, u_B, u_C1, u_C2, u_D)`.

```
m1 (C@u_C1):  links (0.2, 0.2, 0.2, 1, 1, 0, 0, 0.2)    nodes (0.1, 0.1, 1, 0, 0.1)
m2 (C@u_C2):  links (0.2, 0.2, 0.2, 0, 0, 1, 1, 0.2)    nodes (0.1, 0.1, 0, 1, 0.1)
```

---

## 2. Capacity: why the mixture is forced (analytic target λ* = 1)

By the single-execution semantics, one valid mapping runs `C` at a **single** node. So:

- **Any single mapping** puts the whole heavy computation on one `0.5`-capacity node:
  `λ · r^C = λ ≤ 0.5`  ⟹  **single-mapping capacity = 0.5**.
- **The equal mixture** `f_{m1} = f_{m2} = 0.5` splits `C` across `u_C1` and `u_C2`, each seeing
  `0.5 · λ · r^C ≤ 0.5`  ⟹  `λ ≤ 1`. So **λ\* = 1**, attained only at the 50/50 mixture.

The wireless links are deliberately provisioned so they do **not** bind at λ = 1: at the 50/50
mixture each `C`-branch link carries a load of `0.5`, versus an average service of
`0.85 · 2 = 1.7`; and the primary-interference bottleneck at `u_A` (and symmetrically `u_D`)
needs `0.2 + 0.2 + 0.5 + 0.5 = 1.4` workload/slot against a per-slot service of `2`, feasible
with slack. Hence the LP boundary is set by the parallel `C`-computation, while the ON/OFF
states and the primary-interference matching are active every slot.

**Sanity check to run first:** solve the state-averaged capacity LP (Section 2.2) by enumerating

- the **2 valid mappings**,
- all **2⁴ = 16 wireless states** of links 4–7,
- all feasible primary-interference activations per state,

maximizing `λ` subject to constraints (1)–(3). It should return **λ\* = 1.000** (to LP
tolerance), with optimal mapping rates `f_{m1} = f_{m2} = 0.5`. If it returns noticeably below
1.0, the wireless links are binding — raise their capacity from 2 toward 3 until λ\* = 1.0, and
tell me the value you used so I update the paper.

---

## 3. Runs to perform

Use the **existing DCNC-DAG simulator** with `T_f = 1` and **exact enumeration** of the two
mappings (queue-priced min-cost), the same code path as the old 7.2 run. Bounded arrivals
`A(t) = ⌊λ⌋ + Bern(λ − ⌊λ⌋)`; empty initial state.

### 3.1 Main sweep (fills Table 3)

- Offered rates `ρ · λ*` for `ρ ∈ {0.95, 0.98, 0.99, 1.01, 1.03, 1.05, 1.10}` (so, since
  λ\* = 1, the offered rates are `0.95, 0.98, 0.99, 1.01, 1.03, 1.05, 1.10`).
- **Horizon 10⁵ slots, seeds {0,1,2,3,4}** (5 seeds), report seed-means.
- Per (ρ, seed) record:
  - `λ_out` = completed throughput (completed requests / T),
  - completion ratio `κ(T) / A(T)`,
  - **realized share of `m1`** = (# arrivals served by `m1`) / (total arrivals),
  - second-half least-squares slope of total **physical** backlog and total **virtual** backlog
    (workload units per slot).

### 3.2 Single-mapping ablation (the "mixture is necessary" money check)

Re-run the **same instance and sweep**, but **force the policy to always use `m1`** (disable
`m2`; i.e., restrict the mapping set to `{m1}`). Everything else identical.

Expected: `λ_out` saturates at **≈ 0.5** — half the boundary — with the completion ratio
collapsing above `λ = 0.5`. This is the direct demonstration that no single valid mapping
attains the boundary and the queue-priced mixing is what doubles it. Keep one summary number
(e.g. the ablation's `λ_out` at `λ = 0.99`, which should be ≈ 0.5) for the prose.

---

## 4. Expected results / success criteria

If the design is right, you should see:

| ρ (= offered rate) | λ_out | completion ratio | share m1 |
|---|---|---|---|
| 0.95 | ≈ 0.95 (tracks input) | ≈ 1.00 | ≈ 0.50 |
| 0.98 | ≈ 0.98 | ≈ 1.00 | ≈ 0.50 |
| 0.99 | ≈ 0.99 | ≈ 1.00 | ≈ 0.50 |
| 1.01 | just below 1.0 | drops below 1 | ≈ 0.50 |
| 1.03 | just below 1.0 | drops further | ≈ 0.50 |
| 1.05 | just below 1.0 | drops further | ≈ 0.50 |
| 1.10 | just below 1.0 | lowest | ≈ 0.50 |

Key qualitative outcomes the paper text asserts (please confirm):

1. For `ρ ≤ 1`: `λ_out` tracks `ρλ*` with completion ratio near one, and **mapping shares stay
   near 0.5/0.5** — the queue-priced policy recovers the LP mixture without being told it.
2. For `ρ > 1`: `λ_out` saturates just below the boundary, completion ratio falls, and the
   second-half backlog slope (physical or virtual) **crosses the fixed `5×10⁻²`
   workload-units-per-slot cutoff** (the backlog check). Report where it first crosses.
3. **Ablation:** single fixed mapping caps `λ_out` at ≈ 0.5.
4. From the overloaded points, note **how far beyond the boundary** the diagnostics first flag
   overload reliably (the old instance gave ≈ 3%). This number becomes the concrete meaning of
   the "few percent" resolution of `λ̂` — send it to me so I can state it precisely (right now the
   paper says "a few percent").

---

## 5. What to send back

To finalize the paper I need:

- the filled **Table 3** (λ_out, completion ratio, share m1, all seed-means; and the seed
  standard errors so I can restore the "standard error ≤ …" note),
- the LP-returned **λ\*** (should be 1.000; if you had to bump link capacity, the value used),
- the **backlog-slope numbers** at a couple of overloaded ρ (to confirm the `5×10⁻²` crossing),
- the **ablation** `λ_out` (≈ 0.5),
- the **resolution** figure (how many % beyond the boundary overload is first flagged).

I will then drop these into Sec. 7.2 (main) and the Sec. S5.2 table/prose (supplement), which
are already written around this instance with the numbers left as `TBD`.

---

## 6. Reproducibility notes

- Fixed instance: a run is `(instance, policy, T_f=1, seed, offered rate)` and reproduces
  exactly, matching the reproducibility convention of Sec. 7.1.
- Same seeds drive the main sweep and the ablation, so the comparison is paired.
- The wireless ON/OFF sample path for the four `C`-branch links is generated i.i.d. Bernoulli(0.85)
  per link per slot, drawn from the run seed; hold it identical across the main run and the
  ablation at each seed.
