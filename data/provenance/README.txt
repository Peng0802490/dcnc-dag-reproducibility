Archived experiment provenance

protocol.json is the original campaign protocol, including historical source
hashes and runtime. It describes the archived executions, not the current
aggregation/plotting scripts. The physical.py and simulator.py source hashes
still match this protocol exactly.

records.csv maps every released record to its original-record SHA-256 and its
current released-record SHA-256. Release records preserve the previous result
and stats values, with the original audit sums, sampled execution checkpoints,
protocol ID and completion timestamp restored. Original server wrapper fields
are not required by the portable reproduction entry point.

recorded_campaign.py.txt preserves the exact passive observer source for audit;
it is not the portable runner. Use scripts/run_campaign.py for new experiments.

The 3,248 physical runs provide completed_request_delay_sum and
pending_registered_request_age_sum. The latter is the sum of horizon minus
arrival-slot index over unfinished registered requests. Asynchronous buffered
requests and injected control wait are zero in these records. These audit sums
allow the finite-horizon lower bound to be recovered without new simulations.
The remaining 380 runs use the separate FIFO/NTO simulator.

Execution checkpoints are sampled 20 times per physical run (64,960 samples);
at each sample there is at most one partially served object per resource.
These samples are not every-slot traces. Small deterministic tests in
tests/test_execution.py also exercise nonpreemption and next-slot successors.

No new experiment matrix was executed for this statistics/plotting refresh.
The archived formal executions completed on 2026-11-01 UTC.
