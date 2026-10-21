import json
# Curves whose sweep topped out while the completion ratio was still high, i.e.
# the grid built from the 4000-slot pilot under-estimated the knee at 2e4 slots.
EXT = {
 ("r6_roofnet","config_random6_Roofnet38_cap210.json"): {
   ("DCNC-DAG","exact_dp"): [2.55,2.75,2.95,3.2,3.45,3.75,4.05,4.4],
   ("DCNC-DAG","greedy"):   [1.85,2.0,2.2,2.4,2.6,2.85,3.1,3.4],
   ("CTS","cts"):           [0.58,0.62,0.67,0.72],
   ("Random","random"):     [0.52,0.56,0.60,0.65]},
 ("r6_flocklab","config_random6_FlockLab_cap210.json"): {
   ("DCNC-DAG","exact_dp"): [3.55,3.85,4.2,4.55,4.95,5.4,5.9,6.4],
   ("DCNC-DAG","greedy"):   [3.55,3.85,4.2,4.55,4.95,5.4,5.9,6.4],
   ("CTS","cts"):           [0.68,0.73,0.79,0.85]},
 ("r6_milan","config_random6_Milan.json"): {
   ("Random","random"):     [0.094,0.101,0.109,0.117,0.126,0.136,0.147,0.16,0.175],
   ("CTS","cts"):           [0.68,0.73,0.79,0.86]},
 ("r6_random","config_random6_Random.json"): {
   ("CTS","cts"):           [0.19,0.205,0.22,0.24,0.26],
   ("Random","random"):     [0.094,0.102,0.111,0.121]},
 ("driving_milan","config_driving_Milan.json"): {
   ("Random","random"):     [0.219,0.234,0.25,0.268]},
}
jobs=[]
for (case,cfg),curves in EXT.items():
    for (p,s),rates in curves.items():
        for seed in [1,2,3]:
            for r in rates:
                jobs.append(dict(case=case,config=cfg,policy=p,solver=s,fixed_k=1,slots=20000,seed=seed,rate=r))
json.dump(jobs,open("sweeps/ext.json","w"),indent=1); print(len(jobs),"jobs")
