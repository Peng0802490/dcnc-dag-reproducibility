"""Recompute summaries, table inputs and figures from recorded runs; no simulation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
DATA=ROOT/'data'
JOBS=ROOT/'inputs/experiments.json'
from dcnc_sim.paper_metrics import REQUEST_METRICS_SCHEMA
from paper_aggregation import aggregate_records

def aggregate(output, runs_dir=DATA/'runs', jobs_file=JOBS):
    jobs = json.loads(Path(jobs_file).read_text(encoding='utf-8'))
    return aggregate_records(jobs, runs_dir, Path(output)/'exports')


def tables(output, timing_csv=DATA/'table6.csv'):
    rows=[]
    for kind,casecol,ratecol in [('main','case','rate'),('frames','case','rate'),('workflow','workflow','total_arrival_rate'),('moe_100000','model','arrival_rate')]:
        df=pd.read_csv(output/'exports'/kind/'summary.csv')
        keys=[casecol,'policy']+(['solver','fixed_k'] if kind in ('main','frames') else [])
        for key,g in df.groupby(keys):
            supported=g[g.completion_ratio>=.95]
            rows.append(dict(campaign=kind,case=key[0],policy=key[1],solver=key[2] if len(key)>2 else '',
                             frame_length=key[3] if len(key)>3 else 1,
                             supported_rate=float(supported[ratecol].max()) if len(supported) else None))
    dest=output/'tables';dest.mkdir(exist_ok=True)
    frame=pd.DataFrame(rows);frame.to_csv(dest/'supported_rates.csv',index=False)
    table5=[]
    for kind,case,title in [('moe_100000','mixtral','MoE Mixtral'),('moe_100000','llama','MoE Llama'),
                           ('workflow','workflow_srasearch22','SRA-Search-22'),('workflow','workflow_sipht31','SIPHT-31')]:
        group=frame[(frame.campaign==kind)&(frame['case']==case)]
        rates=dict(zip(group.policy,group.supported_rate))
        main='DCNC-DAG-H' if kind=='moe_100000' else 'DCNC-DAG'
        baseline=max(v for k,v in rates.items() if k!=main)
        table5.append(dict(setting=title,DCNC_DAG_H=rates[main],baseline_1_policy='Lazarus-style' if kind=='moe_100000' else 'CTS',
                           baseline_1=rates.get('Lazarus-style',rates.get('CTS')),baseline_2_policy='FlexMoE-style' if kind=='moe_100000' else 'Random',
                           baseline_2=rates.get('FlexMoE-style',rates.get('Random')),gain_vs_better_baseline=rates[main]/baseline))
    pd.DataFrame(table5).to_csv(dest/'table5.csv',index=False)
    shutil.copy2(output/'exports/capacity/summary.csv',dest/'capacity.csv')
    if timing_csv is None:
        return
    timing=pd.read_csv(timing_csv)
    timing_rows=[]
    for (case,frame),group in timing.groupby(['case','fixed_k']):
        row=dict(case=case,fixed_k=frame,num_runs=len(group),num_rates=group.total_arrival_rate.nunique(),
                 min_arrival_rate=group.total_arrival_rate.min(),max_arrival_rate=group.total_arrival_rate.max())
        for metric in ('dynvmp_calls','dynvmp_wall_time_sec','simulation_wall_time_sec','avg_delay_completed','avg_delay_with_penalty'):
            row['mean_'+metric]=group[metric].mean()
            row['std_'+metric]=group[metric].std()
            if metric not in ('avg_delay_completed','avg_delay_with_penalty'):
                row['min_'+metric]=group[metric].min();row['max_'+metric]=group[metric].max()
        baseline=timing[(timing['case']==case)&(timing.fixed_k==1)]
        for metric,reduction in (('dynvmp_calls','dynvmp_call_reduction_vs_k1'),
                                 ('dynvmp_wall_time_sec','dynvmp_time_reduction_vs_k1'),
                                 ('simulation_wall_time_sec','simulation_time_reduction_vs_k1')):
            row[reduction]=1-group[metric].mean()/baseline[metric].mean()
        timing_rows.append(row)
    pd.DataFrame(timing_rows).to_csv(dest/'table6.csv',index=False)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'results')
    p.add_argument('--runs-dir',type=Path,default=DATA/'runs',help='Directory containing <job-id>/result.json and FIFO trajectories.')
    p.add_argument('--jobs-file',type=Path,default=JOBS,help='Manifest matching the selected runs.')
    timing=p.add_mutually_exclusive_group()
    timing.add_argument('--timing-csv',type=Path,help='Separate Table 6 timing input; not produced by a campaign.')
    timing.add_argument('--skip-timing',action='store_true')
    p.add_argument('--summaries-only',action='store_true',help='Only export per-run metrics and grouped summaries (also supports partial manifests).')
    p.add_argument('--skip-figures',action='store_true')
    args=p.parse_args();output=args.output.resolve();runs_dir=args.runs_dir.resolve();jobs_file=args.jobs_file.resolve()
    if output==ROOT or any(output.is_relative_to(path) for path in (DATA,ROOT/'inputs',runs_dir)):
        p.error('Choose an output directory outside the supplied data, inputs and runs directory.')
    timing_csv=args.timing_csv.resolve() if args.timing_csv else None
    if timing_csv is None and not args.skip_timing and runs_dir==(DATA/'runs').resolve():
        timing_csv=DATA/'table6.csv'
    if args.summaries_only:
        timing_csv=None
    if timing_csv is None and (output/'tables/table6.csv').exists():
        p.error('This output contains an old Table 6. Choose a fresh output directory or explicitly supply --timing-csv.')
    output.mkdir(parents=True,exist_ok=True)
    groups=aggregate(output,runs_dir,jobs_file)
    points_count=0
    if not args.summaries_only:
        tables(output,timing_csv)
        from plot_figures import select_points,render
        points=select_points(output/'exports')
        figures=output/'figures';figures.mkdir(exist_ok=True)
        points.to_csv(figures/'points.csv',index=False)
        points_count=len(points)
        from plot_figures import write_selection
        write_selection(output/'exports', figures)
        if not args.skip_figures: render(points,output)
    provenance=dict(request_metrics_schema=REQUEST_METRICS_SCHEMA,runs_dir=str(runs_dir),jobs_file=str(jobs_file),
                    timing_csv=str(timing_csv) if timing_csv else None,
                    jobs=sum(map(len,groups.values())),simulations_run=0)
    (output/'aggregation_inputs.json').write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(output),curve_points=points_count,**provenance)))

if __name__=='__main__': main()
