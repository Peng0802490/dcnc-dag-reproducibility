"""Recompute summaries, table inputs and figures from recorded runs; no simulation."""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
DATA=ROOT/'data'
JOBS=ROOT/'inputs/experiments.json'

def aggregate(output):
    groups=defaultdict(list)
    for job in json.loads(JOBS.read_text()):
        record=json.loads((DATA/'runs'/job['id']/'result.json').read_text())
        row=dict(record['result'])
        if job['kind'] in ('main','frames','workflow'):
            stats=record['stats']
            assert stats['total_service_units']==stats['completed_service_units']+stats['pending_service_units']
            # One request completes only when every sink output is delivered.
            row['avg_delay_completed']=stats['avg_service_delay_completed']
            ratio=stats['completed_service_units']/stats['total_service_units']
            row['completion_ratio']=ratio
            if job['kind']=='workflow':row['job_completion_ratio']=ratio
        groups[job['kind']].append(row)
    for kind,rows in groups.items():
        dest=output/'exports'/kind;dest.mkdir(parents=True,exist_ok=True)
        df=pd.DataFrame(rows)
        df.to_csv(dest/'runs.csv',index=False)
        if kind in ('main','frames'):
            result=df.groupby(['case','policy','solver','fixed_k','rate'],as_index=False).agg(
                seeds=('seed','size'),avg_delay_completed=('avg_delay_completed','mean'),
                delay_se=('avg_delay_completed','sem'),completion_ratio=('completion_ratio','mean'))
        elif kind=='workflow' or kind.startswith('moe_'):
            keys=['workflow','policy','total_arrival_rate'] if kind=='workflow' else ['model','policy','arrival_rate']
            delay='avg_delay_completed' if kind=='workflow' else 'mean_completion_delay'
            cr='job_completion_ratio' if kind=='workflow' else 'completion_ratio'
            for col in (keys[-1],delay,cr): df[col]=pd.to_numeric(df[col])
            agg=dict(seeds=('seed','size'),avg_delay_completed=(delay,'mean'),delay_se=(delay,'sem'),completion_ratio=(cr,'mean'))
            if kind=='moe_100000': agg['mean_lower_bound']=('mean_service_delay_lower_bound','mean')
            result=df.groupby(keys,as_index=False).agg(**agg)
        elif kind=='capacity':
            from run_new_7_2_wireless_mixed_mapping import summarize_runs,verify_paired_arrivals
            verify_paired_arrivals(df)
            result=summarize_runs(df)
        else:
            assert kind=='fifo'
            fifo=dest/'data';fifo.mkdir(exist_ok=True)
            jobs=[j for j in json.loads(JOBS.read_text()) if j['kind']=='fifo']
            for experiment in ('A','B'):
                parts=[pd.read_csv(DATA/'runs'/j['id']/'trajectory.csv') for j in jobs if j['params']['experiment']==experiment]
                pd.concat(parts,ignore_index=True).to_csv(fifo/f'experiment_{experiment}_raw_trajectories.csv',index=False)
            env=dict(os.environ,DCNC_FIFO_DATA_DIR=str(fifo.resolve()))
            subprocess.run([sys.executable,str(ROOT/'scripts/aggregate_backlog.py')],env=env,check=True)
            continue
        result.to_csv(dest/'summary.csv',index=False)
    return groups

def tables(output):
    rows=[]
    for kind,casecol,ratecol in [('main','case','rate'),('frames','case','rate'),('workflow','workflow','total_arrival_rate'),('moe_50000','model','arrival_rate')]:
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
    for kind,case,title in [('moe_50000','mixtral','MoE Mixtral'),('moe_50000','llama','MoE Llama'),
                           ('workflow','workflow_srasearch22','SRA-Search-22'),('workflow','workflow_sipht31','SIPHT-31')]:
        group=frame[(frame.campaign==kind)&(frame['case']==case)]
        rates=dict(zip(group.policy,group.supported_rate))
        main='DCNC-DAG-H' if kind=='moe_50000' else 'DCNC-DAG'
        baseline=max(v for k,v in rates.items() if k!=main)
        table5.append(dict(setting=title,DCNC_DAG_H=rates[main],baseline_1_policy='Lazarus-style' if kind=='moe_50000' else 'CTS',
                           baseline_1=rates.get('Lazarus-style',rates.get('CTS')),baseline_2_policy='FlexMoE-style' if kind=='moe_50000' else 'Random',
                           baseline_2=rates.get('FlexMoE-style',rates.get('Random')),gain_vs_better_baseline=rates[main]/baseline))
    pd.DataFrame(table5).to_csv(dest/'table5.csv',index=False)
    shutil.copy2(output/'exports/capacity/summary.csv',dest/'capacity.csv')
    timing=pd.read_csv(DATA/'table6.csv')
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
    p.add_argument('--skip-figures',action='store_true')
    args=p.parse_args();output=args.output.resolve()
    if output==ROOT or output.is_relative_to(DATA) or output.is_relative_to(ROOT/'inputs'):
        p.error('Choose an output directory outside the supplied data and inputs.')
    output.mkdir(parents=True,exist_ok=True)
    aggregate(output);tables(output)
    from plot_figures import select_points,render
    points=select_points(output/'exports')
    figures=output/'figures';figures.mkdir(exist_ok=True)
    points.to_csv(figures/'points.csv',index=False)
    if not args.skip_figures: render(points,output)
    print(json.dumps(dict(output=str(output),curve_points=len(points),simulations_run=0)))

if __name__=='__main__': main()
