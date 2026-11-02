# Input construction

`python tools/rebuild_inputs.py --check` rebuilds the RoofNet-inspired topology
and both workflow DAGs into `results/rebuilt_inputs/`, and checks all structures,
parameters and metadata against the released inputs. No experiment is rerun.

- RoofNet: seeded geometric placement and radius links, followed by the
  original ordered capacity and endpoint-dynamics rules. Individual commands:
  `generate_roofnet.py`, `rescale_networks.py`, `make_access_dynamic.py`.
  The final capacity/access overlays supersede the early radio-model metadata.
- Workflows: `convert_workflow.py --workflow srasearch22|sipht31 --output PATH`
  reads the public source snapshots and the explicit parameter tables.
  Add `--public-structure` for unadapted public nodes/edges without workloads.
- SRA preserves the public task graph. The released SIPHT service graph changes
  seven dependencies in each direction; `workflow_recipes.json` lists every
  removed and added edge. Existing experiment inputs remain unchanged.
- The node/edge CSVs pair public measurements (where available) with the
  released fixed normalized factors. The historical runtime/byte conversion
  is undocumented. `normalize_workflow_measurements.py` provides the separate
  prospective rules `r=runtime/seconds_per_unit` and
  `xi=shared_bytes/bytes_per_unit`, with optional clipping and explicit scales.
  It does not supply historical derivation evidence. Missing measurements stay
  missing; SIPHT shared-file byte sizes are not available in these sources.

`sources.json` pins source URLs, revision, hashes and archive member names.
Source snapshots are provided for offline reconstruction. SRA source data is
from WfInstances (LGPL-3.0; license texts in `third_party/wfinstances/`).
The SIPHT DOT graph and runtime table come from Pegasus SIPHT Run 1; the gallery
does not separately label this archived run's data license.
