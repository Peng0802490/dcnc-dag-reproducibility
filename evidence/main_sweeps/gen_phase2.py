import json
# Fig.5(b) must sit on the same instance as Fig.3(b): the frame-length curves
# for the random topology are rerun on the qualified-set config, sharing the
# T_f=1 rate grid so the ablation is read across one common x-axis.
def grid(k):
    B=[0.03,0.07,0.13,0.20,0.29,0.39,0.50,0.61,0.71,0.80]
    T=[0.88,0.94,1.00,1.06,1.13,1.21,1.30,1.42,1.55]
    return sorted({round(k*m,4) for m in B+T})
jobs=[]
for k in [4,16,64,256]:
    for seed in [1,2,3]:
        for r in grid(0.55):
            jobs.append(dict(case="drv_rand_q45",config="config_driving_Random_q45.json",
                             policy="DCNC-DAG",solver="exact_dp",fixed_k=k,slots=20000,seed=seed,rate=r))
json.dump(jobs,open("sweeps/phase2.json","w"),indent=1); print(len(jobs),"jobs")
