"""Portable manuscript plots: recorded style geometry, F notation and display rules."""
from pathlib import Path
import json
import os
import subprocess
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT=Path(__file__).resolve().parents[1]
FIGURES=ROOT/'inputs/plots'
WORKFLOWS={'workflow_sipht31':'sipht31_avg_delay_completed','workflow_srasearch22':'srasearch22_avg_delay_completed'}
COLORS=['#1f77b4','#ff7f0e','#2ca02c','#d62728','#9467bd']
LW=1.4*1.10*1.15*1.15*1.4
MS=4.0*1.10*1.15*1.15*1.4
LEGEND=dict(frameon=True,borderaxespad=0,columnspacing=.12,handlelength=.85,handletextpad=.12,borderpad=.16,labelspacing=.16,markerscale=.95)

def truncate(points,max_delay=None,cr_floor=None):
    floor=.45 if cr_floor is None else cr_floor
    kept=[]
    for rate,delay,cr in points:
        if kept and cr<floor: break
        kept.append((rate,delay,cr))
        if max_delay is not None and delay>=max_delay: return kept
    return kept[:max(range(len(kept)),key=lambda i:kept[i][1])+1] if kept else kept

def gate_trim(points,gate=.95):
    ok=[i for i,p in enumerate(points) if p[2]>=gate]
    if not ok:return points
    last=ok[-1]
    return points[:last+2] if last+1<len(points) and points[last+1][1]>points[last][1] else points[:last+1]

def select_points(exports):
    rows=[]
    def add(case,policy,rate,value,se=None,metric='avg_service_delay_completed'):
        rows.append(dict(case=case,policy=policy,rate=rate,delay_se=se,metric=metric,mean=value))
    mapping=json.loads((FIGURES/'policy_map.json').read_text())
    main=pd.read_csv(exports/'main/summary.csv')
    for case,spec in mapping.items():
        def data_for(curve):
            policy,solver,frame=spec['curves'][curve]
            return main[(main['case']==spec['case'])&(main.policy==policy)&(main.solver==solver)&(main.fixed_k==frame)&(main.seeds>=spec.get('min_seeds',1))].sort_values('rate')
        for curve in spec['curves']:
            data=data_for(curve)
            if curve in spec.get('match_grid',{}):data=data[data.rate.isin(data_for(spec['match_grid'][curve]).rate)]
            points=list(data[['rate','avg_delay_completed','completion_ratio']].itertuples(index=False,name=None))
            kept=truncate(points,spec.get('max_delay'),spec.get('cr_floor'))
            drop=spec.get('drop_last',{}).get(curve,0)
            if drop:kept=kept[:-drop] if drop<len(kept) else kept[:1]
            if spec.get('gate_trim'):kept=gate_trim(kept)
            for x,y,cr in kept:
                # Presentation-only omission requested by the authors; raw runs remain.
                if case=='random_flocklab' and curve=='Heuristic.csv' and x==3.12:continue
                add(case,curve.removesuffix('.csv'),x,y)
    workflow=pd.read_csv(exports/'workflow/summary.csv')
    for case in WORKFLOWS:
        for policy,label in [('DCNC-DAG','DCNC-DAG-H'),('CTS','CTS'),('Random','Random')]:
            data=workflow[(workflow.workflow==case)&(workflow.policy==policy)].sort_values('total_arrival_rate')
            points=list(data[['total_arrival_rate','avg_delay_completed','completion_ratio']].itertuples(index=False,name=None))
            selected={p[0] for p in gate_trim(points)}
            for r in data.itertuples():
                if r.total_arrival_rate in selected:add(case,label,r.total_arrival_rate,r.avg_delay_completed,r.delay_se)
    frames=pd.read_csv(exports/'frames/summary.csv')
    for case,stem in [('k100k_milan','driving_milan_K'),('k100k_random','driving_random_K')]:
        for frame in (1,4,16,64,256):
            data=frames[(frames['case']==case)&(frames.fixed_k==frame)].sort_values('rate')
            points=list(data[['rate','avg_delay_completed','completion_ratio']].itertuples(index=False,name=None))
            for x,y,cr in truncate(points,max_delay=4000):
                add(stem,f'F={frame}',x,y,float(data.loc[data.rate==x,'delay_se'].iloc[0]))
    moe=pd.read_csv(exports/'moe_100000/summary.csv')
    for model in ('mixtral','llama'):
        for policy in ('DCNC-DAG-H','Lazarus-style','FlexMoE-style'):
            data=moe[(moe.model==model)&(moe.policy==policy)].sort_values('arrival_rate')
            for r in data.itertuples():
                if model=='llama' and policy=='DCNC-DAG-H' and r.arrival_rate==1.05:continue
                add(model+'_skewed_completed_delay',policy,r.arrival_rate,r.mean_lower_bound,metric='mean_service_delay_lower_bound')
    return pd.DataFrame(rows)

def fonts():
    for name in ('times.ttf','timesi.ttf'):
        p=Path('C:/Windows/Fonts')/name
        if p.exists():font_manager.fontManager.addfont(str(p))
    serif='Times New Roman' if 'Times New Roman' in {f.name for f in font_manager.fontManager.ttflist} else 'DejaVu Serif'
    scale=1.40*1.50*1.10*1.10
    plt.rcParams.update({'font.family':serif,'font.size':9*scale,'axes.labelsize':10*scale,'axes.titlesize':14*scale,
        'xtick.labelsize':8*scale,'ytick.labelsize':8*scale,'legend.fontsize':7.5*scale,'mathtext.fontset':'custom',
        'mathtext.rm':serif,'mathtext.it':serif+':italic','pdf.fonttype':42,'ps.fonttype':42})

def render(points,output):
    fonts();styles=json.loads((FIGURES/'style.json').read_text());dest=output/'figures'
    for case,group in points.groupby('case',sort=False):
        workflow=case in WORKFLOWS
        stem=WORKFLOWS.get(case,case if case.endswith(('_K','_skewed_completed_delay')) else case+'_delay')
        if workflow:
            policies=[('DCNC-DAG-H','DCNC-DAG-H','D'),('CTS','CTS','s'),('Random','Randomized','^')]
        elif case.endswith('_K'):
            policies=[(f'F={f}',rf'$F$={f}',m) for f,m in zip((1,4,16,64,256),('o','s','^','D','v'))]
        elif case.endswith('_skewed_completed_delay'):
            policies=[('DCNC-DAG-H','DCNC-DAG-H','D'),('Lazarus-style','Lazarus-inspired','s'),('FlexMoE-style','FlexMoE-inspired','^')]
        else:
            policies=[('Exact-K1',r'DCNC-DAG ($F$=1)','o'),('CTS','CTS','s'),('Randomized','Randomized','^'),('Heuristic','DCNC-DAG-H','D')]
        spec=styles[stem];fig=plt.figure(figsize=spec['figsize']);ax=fig.add_axes(spec['axes'])
        xmax=ymax=0
        for (policy,label,marker),color in zip(policies,COLORS):
            data=group[group.policy==policy].sort_values('rate');assert len(data)
            x=data.rate.to_numpy();y=data['mean'].to_numpy();se=data.delay_se.fillna(0).to_numpy()
            ax.plot(x,y,label=label,marker=marker,color=color,linewidth=LW,markersize=MS)
            if workflow or case.endswith('_K'):ax.fill_between(x,y-se,y+se,color=color,alpha=.15,linewidth=0)
            xmax=max(xmax,float(x.max()));ymax=max(ymax,float((y+se).max()))
        moe=case.endswith('_skewed_completed_delay')
        ylabel='Request delay lower bound (slots)' if moe else 'Avg. completion delay (slots)'
        ax.set(xlabel='Arrival rate',ylabel=ylabel,xlim=(0,xmax*1.05),ylim=(0,ymax*1.03))
        if moe:ax.yaxis.label.set_fontsize(ax.yaxis.label.get_fontsize()*.96)
        ax.grid(True,alpha=.3)
        for spine in ax.spines.values():spine.set_linewidth(.9)
        ax.tick_params(width=.9,length=3.5)
        ax.legend(loc='lower center',bbox_to_anchor=(.5,1.05),ncol=3 if case.endswith('_K') else 2,**LEGEND)
        for ext in ('pdf','png'):fig.savefig(dest/(stem+'.'+ext),dpi=300)
        plt.close(fig)
    env=dict(os.environ,DCNC_FIGURE_OUTPUT=str(dest.resolve()),DCNC_FIFO_DATA=str((output/'exports/fifo/data/experiment_B_aggregate_trajectories.csv').resolve()))
    subprocess.run([sys.executable,str(ROOT/'scripts/plot_backlog.py')],check=True,env=env)
