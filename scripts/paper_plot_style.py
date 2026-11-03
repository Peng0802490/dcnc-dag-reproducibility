"""Render the ten approved manuscript panels with the MoE reference typography."""
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter


CONFIG = json.loads((Path(__file__).resolve().parents[1] /
                     'inputs/plots/paper_style.json').read_text())
Y_LABEL = 'Avg. completion delay (slots)'


def render_paper_panel(spec, curves, directory, serif, check_layout):
    kind, scenario, stem, title, policies = spec
    panel = CONFIG['figures'][stem]
    style = CONFIG['style']
    width, height = CONFIG['page_dimensions_pt']
    left, top, right, bottom = CONFIG['axes_box_top_left']
    settings = {
        'font.family': serif, 'font.size': 22.869,
        'axes.labelsize': style['xlabel_pt'], 'axes.titlesize': 35.574,
        'xtick.labelsize': style['ticks_pt'], 'ytick.labelsize': style['ticks_pt'],
        'legend.fontsize': style['legend_pt'], 'mathtext.fontset': 'custom',
        'mathtext.rm': serif, 'mathtext.it': serif + ':italic',
        'pdf.fonttype': 42, 'ps.fonttype': 42, 'savefig.facecolor': 'white',
    }
    with plt.rc_context(settings):
        fig = plt.figure(figsize=(width / 72, height / 72))
        ax = fig.add_axes([left / width, (height - bottom) / height,
                           (right - left) / width, (bottom - top) / height])
        for curve in curves[stem]:
            ax.plot(curve['x'], curve['y'], label=curve['label'],
                    marker=curve['marker'], color=curve['color'],
                    linewidth=style['linewidth_pt'], markersize=style['markersize_pt'])
            ax.fill_between(curve['x'], curve['y'] - curve['se'],
                            curve['y'] + curve['se'], color=curve['color'],
                            alpha=.13, linewidth=0, zorder=1)
        ax.set(xlabel='Arrival rate', ylabel=Y_LABEL,
               xlim=panel['xlim'], ylim=panel['ylim'])
        ax.yaxis.label.set_fontsize(style['ylabel_pt'])
        ax.grid(True, alpha=style['grid_alpha'])
        for spine in ax.spines.values():
            spine.set_linewidth(style['spine_width_pt'])
        ax.tick_params(width=style['tick_width_pt'], length=style['tick_length_pt'])
        legend = ax.legend(loc='lower center', bbox_to_anchor=(.5, 1.05),
                           ncol=3 if kind == 'frames' else 2, **style['legend'])
        visible = [tick for tick in ax.get_yticks()
                   if ax.get_ylim()[0] <= tick <= ax.get_ylim()[1]]
        scientific = max(abs(tick) for tick in visible) >= 10000
        formatter = ScalarFormatter(useMathText=scientific, useOffset=False)
        formatter.set_scientific(scientific)
        if scientific:
            formatter.set_powerlimits((0, 0))
            ax.yaxis.get_offset_text().set_ha('right')
            ax.yaxis.get_offset_text().set_x(0)
        ax.yaxis.set_major_formatter(formatter)
        ax.xaxis.set_label_coords(*CONFIG['xlabel_coordinates'], transform=fig.transFigure)
        ax.yaxis.set_label_coords(*CONFIG['ylabel_coordinates'], transform=fig.transFigure)
        layout = check_layout(fig, [ax], [legend], stem)
        layout.update(xlim=list(ax.get_xlim()), ylim=list(ax.get_ylim()),
                      paper_pdf=panel['filename'])
        pdf = directory / panel['filename']
        fig.savefig(pdf, format='pdf', metadata={
            'Title': title + ' - request delay lower bound',
            'Subject': 'Approved lower-bound figures; final arrival-rate tail selection.',
            'CreationDate': None, 'ModDate': None,
        })
        png = directory / (stem + '.png')
        temporary = png.with_suffix('.rendering.png')
        fig.savefig(temporary, dpi=300)
        temporary.replace(png)
        plt.close(fig)
    return [pdf, png], layout
