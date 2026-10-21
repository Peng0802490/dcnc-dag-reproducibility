import json
jobs=[]
POL=[("DCNC-DAG","exact_dp"),("DCNC-DAG","greedy"),("CTS","cts"),("Random","random")]
def grid(k):
    B=[0.03,0.07,0.13,0.20,0.29,0.39,0.50,0.61,0.71,0.80]
    T=[0.88,0.94,1.00,1.06,1.13,1.21,1.30,1.42,1.55]
    return sorted({round(k*m,4) for m in B+T})
# (1) Fig 3(b) candidate: driving on the random topology with function-specific
#     qualified sets.  Four-policy check that the baseline ordering survives.
KNEE={"DCNC-DAG/exact_dp":0.55,"DCNC-DAG/greedy":0.46,"CTS/cts":0.20,"Random/random":0.12}
for p,s in POL:
    for seed in [1,2,3]:
        for r in grid(KNEE[p+"/"+s]):
            jobs.append(dict(case="drv_rand_q45",config="config_driving_Random_q45.json",policy=p,solver=s,
                             fixed_k=1,slots=20000,seed=seed,rate=r))
# (2) FlockLab variants: the rescaled net makes DCNC reach 3.0 while CTS dies at
#     0.5, so the four thresholds span 300x and cannot share a linear axis.
#     Compare against the original unit-capacity net and against random5.
for case,cfg,kn in [("fl_cap1_r6","config_random6_FlockLab.json",
                     {"DCNC-DAG/exact_dp":0.32,"DCNC-DAG/greedy":0.32,"CTS/cts":0.06,"Random/random":0.02}),
                    ("fl_cap210_r5","config_random5_FlockLab_cap210.json",
                     {"DCNC-DAG/exact_dp":3.0,"DCNC-DAG/greedy":2.1,"CTS/cts":0.75,"Random/random":0.05})]:
    for p,s in POL:
        for r in grid(kn[p+"/"+s]):
            jobs.append(dict(case=case,config=cfg,policy=p,solver=s,fixed_k=1,slots=20000,seed=1,rate=r))
json.dump(jobs,open("sweeps/followup.json","w"),indent=1); print(len(jobs),"jobs")
