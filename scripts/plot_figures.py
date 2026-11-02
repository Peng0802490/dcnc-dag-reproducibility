"""Plot verified request-delay lower bounds with explicit user-requested tail cuts."""
from pathlib import Path
from collections import defaultdict
import csv
import hashlib
import json
import math
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import MaxNLocator, ScalarFormatter, LogLocator, NullFormatter
import numpy as np

import os
import subprocess
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
Y_LABEL = 'Request delay lower bound (slots)'
COLORS = ['#1f77b4','#ff7f0e','#2ca02c','#d62728','#9467bd']
TAIL_TRIM = json.loads((ROOT/'inputs/plots/policy_map.json').read_text())['tail_trim']

def read_csv(path):
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))

main_curves=[('DCNC-DAG','exact_dp',1,r'DCNC-DAG ($F$=1)','o'),
             ('CTS','cts',1,'CTS','s'),('Random','random',1,'Randomized','^'),
             ('DCNC-DAG','greedy',1,'DCNC-DAG-H','D')]
workflow_curves=[('DCNC-DAG','',1,'DCNC-DAG-H','D'),('CTS','',1,'CTS','s'),('Random','',1,'Randomized','^')]
moe_curves=[('DCNC-DAG-H','',1,'DCNC-DAG-H','D'),('Lazarus-style','',1,'Lazarus-inspired','s'),
            ('FlexMoE-style','',1,'FlexMoE-inspired','^')]
frame_curves=[('DCNC-DAG','exact_dp',f,rf'$F$={f}',m) for f,m in zip((1,4,16,64,256),('o','s','^','D','v'))]
specs=[
    ('main','driving_milan','driving_milan_delay_lower_bound','Autonomous driving - Milan',main_curves),
    ('main','drv_rand_q45','driving_random_delay_lower_bound','Autonomous driving - Random',main_curves),
    ('main','r6_milan','random_milan_delay_lower_bound','Random DAGs - Milan',main_curves),
    ('main','r6_random','random_random_delay_lower_bound','Random DAGs - Random',main_curves),
    ('main','rn_access','random_roofnet_delay_lower_bound','Random DAGs - RoofNet',main_curves),
    ('main','fl_access','random_flocklab_delay_lower_bound','Random DAGs - FlockLab',main_curves),
    ('moe_100000','mixtral','mixtral_skewed_delay_lower_bound','MoE - Mixtral',moe_curves),
    ('moe_100000','llama','llama_skewed_delay_lower_bound','MoE - Llama',moe_curves),
    ('workflow','SRA-Search-22','srasearch22_delay_lower_bound','Workflow - SRA-Search-22',workflow_curves),
    ('workflow','SIPHT-31','sipht31_delay_lower_bound','Workflow - SIPHT-31',workflow_curves),
    ('frames','k100k_milan','driving_milan_F_delay_lower_bound','Frame length - Milan',frame_curves),
    ('frames','k100k_random','driving_random_F_delay_lower_bound','Frame length - Random',frame_curves),
]

def key(row):
    return (row['kind'],row['scenario'],row['policy'],row['solver'],int(row['F']),
            float(row['arrival_rate']),int(row['horizon']))

def prepare(exports):
    exports = Path(exports)
    summaries = read_csv(exports/'delay_lower_bound/summary.csv')
    runs = read_csv(exports/'delay_lower_bound/runs.csv')
    run_groups=defaultdict(list)
    for row in runs:
        n=int(row['arrived_requests'])
        recomputed=(float(row['completed_delay_sum_slots'])+float(row['unfinished_age_sum_slots']))/n
        assert math.isclose(recomputed,float(row['mean_request_delay_lower_bound']),rel_tol=1e-13)
        run_groups[key(row)].append(row)

    points=[];curves={};coverage={}
    for kind,scenario,stem,title,policies in specs:
        curves[stem]=[]
        for (policy,solver,frame,label,marker),color in zip(policies,COLORS):
            selected=sorted([s for s in summaries if (s['kind'],s['scenario'],s['policy'],s['solver'],int(s['F']))
                             ==(kind,scenario,policy,solver,frame)],key=lambda s:float(s['arrival_rate']))
            assert selected, (stem,policy,solver,frame)
            assert len({float(s['arrival_rate']) for s in selected})==len(selected)
            for s in selected:
                raw=run_groups[key(s)]
                assert len(raw)==3 and len({r['seed'] for r in raw})==3
                values=[float(r['mean_request_delay_lower_bound']) for r in raw]
                mean=statistics.mean(values);se=statistics.stdev(values)/math.sqrt(3)
                assert math.isclose(mean,float(s['mean_request_delay_lower_bound']),rel_tol=1e-13)
                assert math.isclose(se,float(s['lower_bound_se']),rel_tol=1e-13,abs_tol=1e-12)
                assert mean-se>0
                points.append(dict(figure=stem,kind=kind,scenario=scenario,policy=policy,solver=solver,F=frame,
                                   arrival_rate=float(s['arrival_rate']),horizon=int(s['horizon']),seeds=3,
                                   mean_request_delay_lower_bound=mean,lower_bound_se=se,
                                   completion_ratio=float(s['mean_completion_ratio'])))
            curves[stem].append(dict(label=label,marker=marker,color=color,policy=policy,solver=solver,F=frame,
                x=np.array([float(s['arrival_rate']) for s in selected]),
                y=np.array([float(s['mean_request_delay_lower_bound']) for s in selected]),
                se=np.array([float(s['lower_bound_se']) for s in selected]),
                horizon=int(selected[0]['horizon'])))
        coverage[stem]=sum(len(c['x']) for c in curves[stem])

    full_points=points
    omitted_keys=set();selection_audit=[]
    for kind,scenario,stem,title,policies in specs:
        for c in curves[stem]:
            count=TAIL_TRIM.get(scenario,{}).get(c['solver'],0)
            if not count:continue
            original_count=len(c['x'])
            assert 0<count<original_count
            removed=c['x'][-count:].tolist()
            for rate in removed:
                omitted_keys.add((stem,c['policy'],c['solver'],c['F'],rate))
            for axis in ('x','y','se'):
                c[axis]=c[axis][:-count]
            selection_audit.append(dict(figure=stem,scenario=scenario,policy=c['policy'],solver=c['solver'],
                label=c['label'],original_points=original_count,removed_points=count,
                remaining_points=len(c['x']),removed_arrival_rates=removed,
                last_remaining_arrival_rate=float(c['x'][-1])))
        coverage[stem]=sum(len(c['x']) for c in curves[stem])
    point_key=lambda p:(p['figure'],p['policy'],p['solver'],p['F'],p['arrival_rate'])
    omitted_points=[p for p in full_points if point_key(p) in omitted_keys]
    points=[p for p in full_points if point_key(p) not in omitted_keys]
    return points, omitted_points, selection_audit, curves, coverage, full_points

def set_style():
    for name in ('times.ttf','timesi.ttf'):
        p=Path('C:/Windows/Fonts')/name
        if p.exists():font_manager.fontManager.addfont(str(p))
    serif='Times New Roman' if 'Times New Roman' in {f.name for f in font_manager.fontManager.ttflist} else 'DejaVu Serif'
    plt.rcParams.update({'font.family':serif,'font.size':15,'axes.labelsize':19,'xtick.labelsize':15,
        'ytick.labelsize':15,'legend.fontsize':14,'mathtext.fontset':'stix','pdf.fonttype':42,'ps.fonttype':42,
        'axes.linewidth':1.0,'savefig.facecolor':'white'})

    return serif

def draw(ax,spec,curves,scale='linear',small=False):
    kind,scenario,stem,title,policies=spec
    for c in curves[stem]:
        ax.plot(c['x'],c['y'],label=c['label'],marker=c['marker'],color=c['color'],
                linewidth=1.8 if small else 2.3,markersize=4.2 if small else 6.6,
                markeredgewidth=.5,zorder=3)
        ax.fill_between(c['x'],c['y']-c['se'],c['y']+c['se'],color=c['color'],alpha=.13,linewidth=0,zorder=2)
    xmax=max(c['x'].max() for c in curves[stem])
    ymax=max((c['y']+c['se']).max() for c in curves[stem])
    ax.set(xlabel='Arrival rate',ylabel=Y_LABEL,xlim=(0,xmax*1.04))
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5,min_n_ticks=3))
    if scale=='linear':
        ax.set_ylim(0,ymax*1.07)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5,min_n_ticks=3))
        fmt=ScalarFormatter(useMathText=True)
        fmt.set_powerlimits((0,0))
        ax.yaxis.set_major_formatter(fmt)
    else:
        ymin=min((c['y']-c['se']).min() for c in curves[stem])
        ax.set_yscale('log');ax.set_ylim(ymin*.8,ymax*1.3)
        ax.yaxis.set_major_locator(LogLocator(base=10,numticks=5))
        ax.yaxis.set_minor_formatter(NullFormatter())
    ax.grid(True,which='major',alpha=.24,linewidth=.8)
    ax.tick_params(width=1.0,length=4)
    fs=10.7 if small else 14
    legend=ax.legend(loc='lower center',bbox_to_anchor=(.5,1.055),ncol=3 if kind=='frames' else 2,
        fontsize=fs,frameon=True,handlelength=1.05,handletextpad=.22,columnspacing=.60,
        borderpad=.24,labelspacing=.25,borderaxespad=0,markerscale=.90)
    legend.get_frame().set_edgecolor('#d0d0d0')
    if small:
        ax.set_xlabel('Arrival rate',fontsize=12)
        ax.set_ylabel(Y_LABEL,fontsize=11)
        ax.tick_params(labelsize=11)
        ax.yaxis.get_offset_text().set_fontsize(10)
    return legend

def record_layout(fig,axes,legends,stem):
    fig.canvas.draw()
    renderer=fig.canvas.get_renderer();W,H=fig.bbox.width,fig.bbox.height
    failures=[]
    for ax,legend in zip(axes,legends):
        xticks=[t for x,t in zip(ax.get_xticks(),ax.get_xticklabels()) if ax.get_xlim()[0]<=x<=ax.get_xlim()[1]]
        yticks=[t for y,t in zip(ax.get_yticks(),ax.get_yticklabels()) if ax.get_ylim()[0]<=y<=ax.get_ylim()[1]]
        artists=[ax.xaxis.label,ax.yaxis.label,ax.yaxis.get_offset_text(),legend,*xticks,*yticks]
        for item in artists:
            if not item.get_visible():continue
            box=item.get_window_extent(renderer)
            if box.x0<-1 or box.y0<-1 or box.x1>W+1 or box.y1>H+1:
                failures.append(dict(artist=type(item).__name__,bounds=list(box.extents)))
    assert not failures, (stem,failures)
    return dict(figure=stem,canvas=[W,H],out_of_bounds=failures)

def save_png(fig, path, dpi):
    # Atomic replacement also works when the target image is open in a viewer.
    temporary = path.with_suffix('.rendering.png')
    fig.savefig(temporary, dpi=dpi)
    temporary.replace(path)

def select_points(exports):
    return pd.DataFrame(prepare(exports)[0])

def write_selection(exports, figures):
    points, omitted, selection, curves, coverage, full_points = prepare(exports)
    figures = Path(figures)
    figures.mkdir(parents=True, exist_ok=True)
    for name, rows in [('points.csv', points), ('all_points.csv', full_points), ('omitted_tail_points.csv', omitted)]:
        pd.DataFrame(rows).to_csv(figures/name, index=False)
    (figures/'tail_trim_selection.json').write_text(json.dumps(selection, indent=2)+'\n', encoding='utf-8')

def render(points, output):
    output = Path(output)
    selected, omitted, selection, curves, coverage, full_points = prepare(output/'exports')
    if points.to_dict('records') != selected:
        raise ValueError('Selected figure points disagree with the raw-data exports')
    figures = output/'figures'
    figures.mkdir(parents=True, exist_ok=True)
    write_selection(output/'exports', figures)
    serif = set_style()
    outputs, layouts = [], []
    for spec in specs:
        fig=plt.figure(figsize=(6.4,4.95))
        ax=fig.add_axes([.19,.18,.78,.59])
        legend=draw(ax,spec,curves)
        layouts.append(record_layout(fig,[ax],[legend],spec[2]))
        p=figures/(spec[2]+'.png');save_png(fig,p,dpi=300);outputs.append(p)
        plt.close(fig)

    # Two root-level contact sheets: same points, alternative y-axis display only.
    for scale in ['linear','log']:
        fig,axes=plt.subplots(4,3,figsize=(18,18.4))
        fig.subplots_adjust(left=.075,right=.985,bottom=.045,top=.875,wspace=.36,hspace=.72)
        legends=[]
        for i,(ax,spec) in enumerate(zip(axes.flat,specs)):
            legends.append(draw(ax,spec,curves,scale=scale,small=True))
            ax.set_title(chr(ord('a')+i)+') '+spec[3],fontsize=14,pad=67,weight='bold')
            T=curves[spec[2]][0]['horizon']
            ax.text(.98,.965,f'T = {T:,}',transform=ax.transAxes,ha='right',va='top',fontsize=10,
                    bbox=dict(facecolor='white',edgecolor='none',alpha=.78,pad=2))
        fig.suptitle('Request delay lower bound - '+('linear' if scale=='linear' else 'logarithmic')+' y-axis',fontsize=24,y=.982)
        fig.text(.5,.958,'Selected arrival-rate ranges | Mean of 3 seeds | Shading: +/- 1 standard error',ha='center',fontsize=14)
        stem='delay_lower_bound_overview' if scale=='linear' else 'delay_lower_bound_log_overview'
        layouts.append(record_layout(fig,list(axes.flat),legends,stem))
        p=figures/(stem+'.png');save_png(fig,p,dpi=150);outputs.append(p);plt.close(fig)

    manifest = dict(points=len(selected), runs_used=len(selected)*3, original_points=len(full_points),
                    omitted_points=len(omitted), figures=12, output_format='png',
                    seed_aggregation='equal-weight', uncertainty='plus/minus 1 standard error',
                    display_selection='explicit largest-arrival-rate tail cuts; full data retained',
                    tail_trim_by_scenario_and_solver=TAIL_TRIM,
                    metric='request_delay_lower_bound', font=serif, coverage=coverage,
                    layout_checks=layouts,
                    outputs={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in outputs})
    (figures/'plot_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    env = dict(os.environ, DCNC_FIGURE_OUTPUT=str(figures),
               DCNC_FIFO_DATA=str(output/'exports/fifo/data/experiment_B_aggregate_trajectories.csv'),
               FIG6_STEM='FIFO_simulation')
    subprocess.run([sys.executable, str(ROOT/'scripts/plot_backlog.py')], env=env, check=True)
