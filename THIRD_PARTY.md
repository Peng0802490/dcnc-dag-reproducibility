# Third-party software and external requirements

## Vendored source snapshots

- `third_party/alib`: alib for Python 2.7, originally published at
  <https://github.com/vnep-approx/alib>. MIT licensed; the original `LICENSE`
  is preserved in that directory.
- `third_party/vnep_approx`: VNEP approximation and DynVMP implementation,
  originally published at <https://github.com/vnep-approx/vnep-approx>. MIT
  licensed; the original `LICENSE` is preserved in that directory.

The server copies had no `.git` directories, so an upstream commit identifier
could not be recovered. `manifests/files.json` and `SHA256SUMS.txt` identify
the exact source snapshots used by this artifact. Generated `*.egg-info`
metadata and an unrelated topology-conversion log were excluded; executable
source and the original license files are retained.

## Bundled and adapted research data

### Internet Topology Zoo

The byte-pinned alib snapshot contains 261 GML and 261 GraphML files under
`third_party/alib/alib/data/topologyZoo_orig/`. They originate from the
[Internet Topology Zoo](https://topology-zoo.org/), created by Simon Knight,
Hung X. Nguyen, Nickolas Falkner, Rhys Bowden, and Matthew Roughan. The dataset
is licensed under the
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)
license; the current upstream license text is available in the
[official repository](https://github.com/mroughan/InternetTopologyZoo/blob/main/LICENSE).
The short attribution file shipped in the server snapshot remains unmodified.
No Topology Zoo data were used to generate the paper-facing claims in this
artifact; the files are retained solely to preserve the exact DynVMP dependency
snapshot.

### FlockLab link-quality data

The FlockLab network files are adaptations of *Wireless Link Quality Estimation
on FlockLab - and Beyond*, version v1.0.0, by Romain Jacob, Reto Da Forno,
Roman Trüb, Andreas Biri, and Lothar Thiele, DOI
[10.5281/zenodo.3354718](https://doi.org/10.5281/zenodo.3354718). The source
dataset is licensed under the
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)
license. The adapted files use `2019-07_FlockLab_sky.csv` (official MD5
`819ed76ca1680fc7857a82a62a50e830`) to retain directed node pairs with positive
mean reception, aggregate packet reception into `p_on`, and add normalized
simulator capacities. The `cap210` and `access` variants make additional,
documented capacity and dynamic-edge transformations. These changes are by the
DCNC-DAG artifact authors and are not measurements supplied by the dataset
creators.

### Workflow structure references

`legacy_inputs/DAG/workflow_srasearch22.json` is a first-party service-DAG
adaptation of `srasearch-chameleon-10a-004.json` from
[wfcommons/WfInstances](https://github.com/wfcommons/WfInstances), whose
repository is licensed under the GNU Lesser General Public License v3.0. The
artifact keeps the public task/dependency pattern, while its service-function
schema and normalized `r`/`xi` factors are DCNC-DAG transformations.

`legacy_inputs/DAG/workflow_sipht31.json` is a first-party structural
reconstruction of the public
[Pegasus Workflow Gallery SIPHT Run 1](https://pegasus.isi.edu/workflow_gallery/gallery/sipht/index.php).
Pegasus is distributed under the
[Apache License 2.0](https://pegasus.isi.edu/about/license/); the Gallery page
does not separately label the archived run.
No raw WfInstances JSON or Pegasus Gallery archive is redistributed in this artifact: only the
task/dependency structures and first-party normalized simulation factors are
included.

`manifests/third_party.json` pins these notices, source identifiers, license
files, adapted-file hashes, and the Topology Zoo file counts. The normal
integrity check fails if a required notice or pinned source relationship is
removed.

## Not redistributed

- Gurobi / `gurobipy`: required by the original Python 2 DynVMP execution path
  and some optional LP checks. It is proprietary software and requires the
  user's own installation and license.
- Times New Roman fonts: not redistributed. Plot scripts fall back to DejaVu
  Serif when compatible fonts are unavailable; numeric plot data are unchanged,
  but typography may differ from the paper PDF.
- Conda and Python packages listed in the environment files remain under their
  respective upstream licenses.

Selecting a first-party top-level license does not replace or narrow any of the
licenses and attribution duties listed above.
