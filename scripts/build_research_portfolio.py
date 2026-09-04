#!/usr/bin/env python3
"""Build accessible, source-linked research figures and the shared story surfaces.

Figures use published aggregates only. No licensed loan records are copied.
The existing interactive explorer and technical project documentation are retained.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = 'https://yangxiaoshawn.github.io/'
SPACE = 'https://shawnchamberlain-open-economic-quant-research-ob-5271962.static.hf.space/'
EVIDENCE = json.loads((ROOT / 'assets/data/evidence.json').read_text())
DETAILS = json.loads((ROOT / 'assets/data/research_details.json').read_text())
REV = EVIDENCE['dataset_revision']
INK, BLUE, ORANGE, GREY = '#16243a', '#2458cc', '#b65520', '#8699b4'
ORDER = ['casuallab', 'macroeconomics', 'realestate', 'tariff-incidence', 'microstructure']
STORIES = {
    'casuallab': dict(topic='Experiments & incentives', title='Who should get the offer?',
        why='A discount can increase activity. The harder question is whether a model can identify who will respond—and spend the same budget better.',
        finding='The complex targeting model has not earned its advantage.',
        method='I test effect estimates against known answers, then compare spending rules at the same budget in simulated markets held out from training.',
        takeaway='The learner misses the recovery benchmark. In the budget experiment, a uniform allocation also produces more incremental trips than the model-based rule.',
        boundary='Semi-synthetic validation, not a measured effect of a real NYC promotion. The oracle knows the true average effect; it is a test benchmark, not a deployable policy.',
        short='Targeting offers', fact='Simple baselines win this test', folder='CasualLab'),
    'macroeconomics': dict(topic='Forecasting & information', title='Would the forecast work in real time?',
        why='Economic statistics are revised after publication. A model can look better in hindsight if its backtest uses numbers no one knew at the time.',
        finding='Changing the data vintage changes which models look best.',
        method='I reconstruct official release histories and rerun forecasts with three information rules: data known then, revised values with the same availability, and unrestricted latest values.',
        takeaway='Only the strict as-of rule avoids both future releases and future revisions. Even holding availability fixed, revised values change the GDP ranking of all six models.',
        boundary='The fixed-mask comparison is a hindsight diagnostic, not a valid real-time forecast. Results describe this pilot and its final holdout; they do not establish a universally best model.',
        short='Real-time forecasts', fact='Data revisions change the ranking', folder='Macroeconomics'),
    'realestate': dict(topic='Housing & household finance', title='Does a cheap mortgage keep a loan in place?',
        why='When a new mortgage costs more than the one a homeowner already has, giving up the old loan becomes expensive. I study whether those loans are less likely to be paid off.',
        finding='Bigger rate gaps are associated with fewer mortgage exits.',
        method='I compare monthly payoff rates across rate gaps, then estimate a complementary log-log hazard model with observed loan and local-market controls.',
        takeaway='The adjusted model reports a hazard ratio of 0.817 for a one-percentage-point larger gap. Unweighted sample shares show the broad ordering, but are not population exit probabilities.',
        boundary='An association, not a causal estimate. Payoff and maturity are pooled; refinancing-related and sale-related payoff cannot be distinguished. Household moves are not observed. This is a selected Freddie Mac sample.',
        short='Mortgage lock-in', fact='Lower rates, fewer loan exits', folder='RealEstate'),
    'tariff-incidence': dict(topic='Trade & public policy', title='Who absorbed the tariff?',
        why='When the U.S. raises import tariffs, foreign suppliers could cut their prices—or importers could pay more. The distinction determines who bears the initial cost.',
        finding='The evidence points toward higher costs for U.S. importers.',
        method='I compare each wave of tariffed products with never-tariffed products, tracking unit import values before and after the policy and checking three sample windows.',
        takeaway='Duty-exclusive unit values show no clear offsetting decline. Duty-inclusive unit values rise. This pattern supports importer-side incidence within the sample.',
        boundary='Unit values are not individual transaction prices. The duty-inclusive measure includes the tariff by construction; the pre-duty series is essential. Quantity fails its date-placebo check.',
        short='Tariff incidence', fact='Import costs rise after duty', folder='TariffIncidence'),
    'microstructure': dict(topic='Market microstructure', title='Can a trading signal survive its costs?',
        why='Predicting a tiny price move is not the same as earning a return. Fees and execution delays can consume the entire apparent advantage.',
        finding='After fees, none of the 144 scenarios remains positive.',
        method='I replay one four-hour BTC/ETH order-book capture across two evaluation phases, four horizons, and nine delay combinations, with a fixed 4 bp fee.',
        takeaway='110 scenarios are positive before fees. The best gross edge is only 2.39 bp, below the 4 bp fee; every net edge is negative.',
        boundary='Exploratory simulation · research reference only · not live trading. The 144 scenarios overlap and are not independent experiments or a portfolio to add together.',
        short='Trading costs', fact='110 positive → 0 after fees', folder='Microstructure'),
}


def esc(value):
    return html.escape(str(value), quote=True)


def source_url(path):
    if path.startswith('assets/'):
        return SITE + path
    return f'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/blob/{REV}/{path}'


def text(x, y, value, size=14, color=INK, anchor='start', weight=400):
    return f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{weight}">{esc(value)}</text>'


def line(x1, y1, x2, y2, color='#dce3ec', width=1, dash=''):
    return f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{color}" stroke-width="{width}"' + (f' stroke-dasharray="{dash}"' if dash else '') + '/>'


def svg(title, body, height=300):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 {height}" role="img" aria-label="{esc(title)}" style="font-family:system-ui,sans-serif"><title>{esc(title)}</title><rect width="600" height="{height}" fill="white"/>{body}</svg>'


def bars(title, labels, values, unit, max_value=None, colors=None, digits=2):
    maximum = max_value or max(values) * 1.2
    height = max(230, len(labels) * 43 + 100)
    left, right, top = 172, 525, 48
    body = text(left, 22, unit, 13, '#59697d')
    for i in range(5):
        x = left + (right-left)*i/4
        body += line(x, top-12, x, height-45)
        body += text(x, height-20, f'{maximum*i/4:g}', 12, '#59697d', 'middle')
    step = (height-100) / max(len(labels), 1)
    for i, (label, value) in enumerate(zip(labels, values)):
        y = top + i*step
        body += text(left-14, y+16, label, 14, INK, 'end')
        w = (right-left)*value/maximum
        body += f'<rect x="{left}" y="{y}" width="{w:.3f}" height="23" rx="2" fill="{(colors or [BLUE]*len(values))[i]}"/>'
        body += text(left+w+8, y+17, f'{value:,.{digits}f}', 14, INK, weight=600)
    return svg(title, body, height)


def plot(title, rows, series, xrange, yrange, xticks, yticks, xlabel, ylabel, intervals=False, event=False):
    left, right, top, bottom = 63, 572, 58, 278
    x = lambda value: left + (value-xrange[0])/(xrange[1]-xrange[0])*(right-left)
    y = lambda value: bottom - (value-yrange[0])/(yrange[1]-yrange[0])*(bottom-top)
    body = text(left, 20, ylabel, 13, '#59697d')
    for value, label in yticks:
        body += line(left, y(value), right, y(value), '#a9b7ca' if value == 0 else '#e2e7ef', 1.4 if value == 0 else 1)
        body += text(left-10, y(value)+4, label, 12, '#59697d', 'end')
    for value, label in xticks:
        body += text(x(value), bottom+22, label, 12, '#59697d', 'middle')
    if event:
        body += line(x(0), top, x(0), bottom, '#8998ad', 1, '4 4') + text(x(0)+7, top+14, 'Tariff begins', 12, '#59697d')
    for key, label, color in series:
        if intervals:
            for row in rows:
                body += line(x(row['x']), y(row[key+'_low']), x(row['x']), y(row[key+'_high']), color, .9)
        points = ' '.join(f'{x(r["x"]):.2f},{y(r[key]):.2f}' for r in rows)
        body += f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.3"/>'
        for row in rows:
            body += f'<circle cx="{x(row["x"]):.2f}" cy="{y(row[key]):.2f}" r="3.5" fill="{color}"/>'
    body += text((left+right)/2, bottom+46, xlabel, 13, '#59697d', 'middle')
    offset=left
    for key, label, color in series:
        body += line(offset, 40, offset+20, 40, color, 3) + text(offset+27, 44, label, 13, color)
        offset += 245
    return svg(title, body, 337)


def chart(cid, title, subtitle, graphic, caption, columns, rows, source):
    return dict(id=cid, title=title, subtitle=subtitle, svg=graphic, caption=caption, columns=columns, rows=rows, source=source)


def build_charts():
    charts = {slug: [] for slug in ORDER}
    casual = EVIDENCE['projects']['casuallab']
    charts['casuallab'].append(chart('effect-recovery','The model misses the simple benchmark','Effect-estimation error · lower is better',
        bars('Effect estimation error: learner 0.0417; constant oracle 0.0247', ['Targeting model','Constant oracle'], [.0417,.0247], 'Root mean squared error (effect units)', .05, [BLUE,GREY],4),
        'The targeting model has more error than a constant benchmark that knows the true average effect. This test does not support a claim that the model reliably identifies who benefits more.',
        ['Estimator','RMSE'], [['Targeting model',.0417],['Constant oracle',.0247]],casual['source']))
    policy = DETAILS['casuallab']['policy']
    charts['casuallab'].append(chart('policy-budget','Equal budgets, no targeting advantage','Incremental trips · eight held-out simulated markets',
        bars('Incremental trips under the same 1000-unit budget', [r['label'] for r in policy], [r['value'] for r in policy], 'Mean incremental trips', 80, [BLUE,GREY,GREY,GREY]),
        'With a budget of 1,000 in each market, the model-based policy averages 64.50 extra trips versus 68.50 for uniform allocation. These are simulated policy outcomes, not field-experiment estimates.',
        ['Allocation rule','Mean incremental trips'], [[r['label'],r['value']] for r in policy],DETAILS['casuallab']['policy_source']))
    macro = EVIDENCE['projects']['macroeconomics']
    rows=[]
    for r in macro['series']:
        rows.append([r['mode'],r['future_eligibility'],r['revised_after_origin']])
    body=text(170,22,'Inputs selected after the forecast date',13,'#59697d')
    for i, (label, first, revision) in enumerate(rows):
        yy=62+i*79
        body+=text(158,yy+18,label,14,INK,'end')
        for j, (v,color) in enumerate([(first,BLUE),(revision,ORANGE)]):
            body+=f'<rect x="174" y="{yy+j*25}" width="{v/7000*340:.3f}" height="17" fill="{color}"/>'
            body+=text(181+v/7000*340,yy+j*25+14,f'{v:,}',13,INK,weight=600)
    body+=text(174,321,'Blue: future release · Orange: future revision',13,'#59697d')
    charts['macroeconomics'].append(chart('information-audit','Hindsight enters through two doors','7,985 feature cells audited under each rule',svg('Future releases and future revisions by information rule',body,345),
        'Strict as-of uses only information known at the time. Fixed mask keeps the original release availability but imports 5,464 later revisions. Unrestricted latest values also introduce 863 future releases. The two counts can overlap; do not add them.',
        ['Information rule','Future-release cells','Future-revision cells'],rows,macro['source']))
    ranks=DETAILS['macroeconomics']['gdp_ranks']
    body=text(110,25,'Strict as-of',14,INK,'middle')+text(385,25,'Revised, fixed mask',14,INK,'middle')
    for rank in range(1,7):
        yy=35+rank*40
        body+=line(110,yy,385,yy,'#edf1f6')+text(90,yy+5,str(rank),14,'#59697d','end')
    for r in ranks:
        color=BLUE if r['label']=='Elastic Net' else ORANGE if r['label']=='AR(1)' else GREY
        y1,y2=35+r['asof_rank']*40,35+r['fixed_rank']*40
        body+=line(110,y1,385,y2,color,2.4)
        body+=f'<circle cx="110" cy="{y1}" r="4" fill="{color}"/><circle cx="385" cy="{y2}" r="4" fill="{color}"/>'
        body+=text(400,y2+5,r['label'],13,color)
    body+=text(110,310,'Rank 1 = lowest forecast error',13,'#59697d')
    charts['macroeconomics'].append(chart('gdp-ranking','All six GDP models change rank','Same availability; different data revisions · 8 final holdout forecasts · horizon 0',svg('GDP model rankings under strict as-of and revised values at fixed availability',body,330),
        'In the final GDP holdout, Elastic Net moves from fourth to first when later revisions replace the original values. AR(1) moves from first to second. Both predictor values and scoring targets are revised, while release availability stays fixed. Eight forecasts (July 2024–April 2026) are too few to establish general model superiority.',
        ['Model','Strict as-of rank','Revised fixed-mask rank'],[[r['label'],r['asof_rank'],r['fixed_rank']] for r in ranks],DETAILS['macroeconomics']['ranks_source']))
    housing=EVIDENCE['projects']['realestate']
    hrs=[dict(x=r['mean_gap'],hazard=r['hazard']) for r in housing['series']]
    model=DETAILS['realestate']['cloglog']
    xpos=lambda value:65+(value-.6)/.6*485
    body=text(65,25,'Adjusted hazard ratio for a +1 percentage-point rate gap',14,'#59697d')
    body+=line(65,156,550,156,'#bdc9da',1.5)+line(xpos(1),55,xpos(1),177,'#8699b4',1,'5 4')
    for value in [.6,.8,1,1.2]:body+=text(xpos(value),185,f'{value:.1f}',13,'#59697d','middle')
    body+=text(xpos(1),47,'1.0 = no association',13,'#59697d','middle')
    body+=f'<circle cx="{xpos(model["hazard_ratio"]):.2f}" cy="156" r="9" fill="{BLUE}"/>'
    body+=text(xpos(model['hazard_ratio']),120,f'{model["hazard_ratio"]:.3f}',30,BLUE,'middle',600)
    body+=text(65,226,'Below 1: lower modeled exit hazard',14,BLUE)
    charts['realestate'].append(chart('mortgage-model','The adjusted association remains negative','Complementary log-log model · estimation sample, 2021–2023',svg('Adjusted mortgage-exit hazard ratio 0.817 compared with no association at 1.0',body,250),
        'A one-percentage-point larger rate gap is associated with an 18.3% lower conditional hazard in this model (1 − 0.817). This is a relative association, not an 18.3-point fall in monthly probability. No confidence interval is displayed; this is not a causal estimate.',
        ['Model','Rate-gap coefficient','Hazard ratio','Loan-months'],[['Complementary log-log',model['coefficient'],model['hazard_ratio'],model['n_loan_months']]],housing['source']))
    charts['realestate'].append(chart('mortgage-gap','The sample shows the broad rate-gap pattern','Unweighted estimation sample · 2021–2023',
        plot('Unweighted exit shares in the estimation sample by mortgage rate gap',hrs,[('hazard','Unweighted sample exit share',BLUE)],(-2.5,4.5),(0,9),[(-2,'−2'),(0,'0'),(2,'+2'),(4,'+4')],[(0,'0%'),(3,'3%'),(6,'6%'),(9,'9%')],'Market rate − existing loan rate (percentage points)','Exit share in sampled loan-months'),
        'Each point is a rate-gap group, placed at its mean gap. The sample overrepresents loans that exit; these unweighted shares are not population monthly probabilities. The downward pattern has reversals and differs from the adjusted model above.',
        ['Rate-gap group','Mean gap (pp)','Unweighted sample exit share (%)','Loan-months'],[[r['bucket'],r['mean_gap'],r['hazard'],r['loan_months']] for r in housing['series']],housing['source']))
    tariff=EVIDENCE['projects']['tariff-incidence']
    trs=[dict(x=i,customs=r['customs'],landed=r['landed']) for i,r in enumerate(tariff['series'])]
    charts['tariff-incidence'].append(chart('tariff-windows','Duty-inclusive costs rise; pre-duty values barely move','Average post-tariff effect across three sample windows',
        plot('Pre-duty and duty-inclusive unit import value effects in three windows',trs,[('customs','Excluding duty',BLUE),('landed','Including duty',ORANGE)],(-.12,2.12),(-.04,.20),[(0,'Aug 2019'),(1,'Dec 2019'),(2,'Feb 2020')],[(-.04,'−0.04'),(0,'0'),(.08,'0.08'),(.16,'0.16')],'Sample ending month','Change in log unit value'),
        'The pre-duty effect stays close to +0.025 log points in all windows, rather than showing a large supplier-side price cut. Duty-inclusive effects stay near +0.15. Unit values are imperfect price proxies.',
        ['Window','Excluding duty (log points)','Including duty (log points)'],[[r['window'],r['customs'],r['landed']] for r in tariff['series']],tariff['source']))
    report=(ROOT/'tariff-incidence/reports/tariff_incidence_results.md').read_text()
    event={}
    for key in ['landed','customs']:
        block=report.split(f'## Stacked multi-wave event study — log_{key}_unit_value (controls: never_treated_products)')[1].split('\n## ')[0]
        for row in block.splitlines():
            fields=[c.strip() for c in row.strip('|').split('|')]
            if len(fields)==7 and re.fullmatch(r'-?\d+',fields[0]):
                xx=int(fields[0]); rec=event.setdefault(xx,{'x':xx})
                rec.update({key:float(fields[1]),key+'_low':float(fields[3]),key+'_high':float(fields[4])})
    ers=[event[k] for k in sorted(event)]
    charts['tariff-incidence'].append(chart('tariff-event','The divergence appears after the tariff','Stacked event study · never-treated products as controls',
        plot('Unit import values before and after a tariff with 95 percent confidence intervals',ers,[('customs','Excluding duty',BLUE),('landed','Including duty',ORANGE)],(-12.5,10.5),(-.1,.27),[(-12,'−12'),(-6,'−6'),(0,'0'),(6,'+6'),(10,'+10')],[(-.1,'−0.1'),(0,'0'),(.1,'0.1'),(.2,'0.2')],'Months relative to tariff implementation','Change in log unit value',intervals=True,event=True),
        'Thin vertical lines show reported 95% intervals. The omitted reference month is −3. Pre-duty values show no sustained offsetting decline; duty-inclusive values rise after treatment. This figure uses the report’s rounded estimates.',
        ['Event month','Excluding duty','CI low','CI high','Including duty','CI low','CI high'],[[r['x'],r['customs'],r['customs_low'],r['customs_high'],r['landed'],r['landed_low'],r['landed_high']] for r in ers],'TariffIncidence/reports/tariff_incidence_results.md'))
    ref=json.loads((ROOT/'assets/data/microstructure_backtest_reference.json').read_text())
    scenarios=sorted(ref['scenarios'],key=lambda r:r['gross_edge_bps'])
    body=text(58,22,'Edge (basis points per unit turnover)',13,'#59697d')
    sx=lambda i:58+i/143*510
    sy=lambda v:277-(v+10)/14*218
    for v in [-8,-4,0,4]:
        body+=line(58,sy(v),568,sy(v),'#9cabbf' if v==0 else '#e2e7ef',1.4 if v==0 else 1)+text(46,sy(v)+4,str(v),12,'#59697d','end')
    body+=line(58,sy(4),568,sy(4),ORANGE,1,'5 4')+text(560,sy(4)-10,'4 bp fee',12,ORANGE,'end')
    for i,r in enumerate(scenarios):
        body+=line(sx(i),sy(r['gross_edge_bps']),sx(i),sy(r['net_edge_bps']),'#dbe3f0',.75)
        for key,color in [('gross_edge_bps',BLUE),('net_edge_bps',ORANGE)]:
            body+=f'<circle cx="{sx(i):.2f}" cy="{sy(r[key]):.2f}" r="2.25" fill="{color}"/>'
    body+=text(58,302,'1',12,'#59697d','middle')+text(568,302,'144',12,'#59697d','middle')+text(315,323,'Scenarios, sorted by gross edge',13,'#59697d','middle')
    body+=text(58,43,'● Before fees',13,BLUE)+text(215,43,'● After fees',13,ORANGE)
    charts['microstructure'].append(chart('trading-all-scenarios','Every scenario falls below zero after fees','All 144 scenarios · fixed fee of 4 bp (0.04%)',svg('Gross and net edge for every one of 144 overlapping simulated trading scenarios',body,340),
        'Each vertical pair is the same scenario before and after the 4 bp fee. Even the best gross edge (2.39 bp) is below the fee. All orange points are below zero. Overlapping scenarios must not be summed.',
        ['Symbol','Phase','Horizon','Decision delay (events)','Order delay (events)','Gross edge (bp)','Net edge (bp)'],[[r['symbol'],r['phase'],r['endpoint'],r['decision_latency_events'],r['order_latency_events'],r['gross_edge_bps'],r['net_edge_bps']] for r in scenarios],'assets/data/microstructure_backtest_reference.json'))
    charts['microstructure'].append(chart('trading-positive','Apparent opportunities disappear after costs','Number of positive scenarios, out of 144',
        bars('110 scenarios positive before fees and zero positive after fees',['Before fees','After 4 bp fee'],[ref['overview']['gross_positive_count'],ref['overview']['net_positive_count']],'Positive scenarios',144,[BLUE,ORANGE],0),
        '110 of 144 scenarios have positive gross results; zero have positive net results. This is a cost check on one four-hour exploratory capture, not a test of live profitability or cross-day reliability.',
        ['Cost treatment','Positive scenarios','Total scenarios'],[['Before fees',110,144],['After fees',0,144]],'assets/data/microstructure_backtest_reference.json'))
    return charts


def figure(c, prefix, full=True):
    caption=f'<p class="figure-reading"><strong>What this shows.</strong> {esc(c["caption"])}</p>'
    table=f'<a class="figure-source" href="{esc(source_url(c["source"]))}">View published source ↗</a>'
    if full:
        headings=''.join('<th scope="col">'+esc(x)+'</th>' for x in c['columns'])
        rows=''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in c['rows'])
        table=f'<details class="figure-values"><summary>View exact values &amp; source</summary><div class="table-wrap"><table><thead><tr>{headings}</tr></thead><tbody>{rows}</tbody></table></div><p>Source: <a href="{esc(source_url(c["source"]))}">{esc(c["source"])}</a></p><a href="{prefix}{c["id"]}.svg" download>Download figure (SVG)</a></details>'
    height=re.search(r'0 0 600 (\d+)',c['svg'])[1]
    return f'<figure class="evidence-figure"><figcaption><h3>{esc(c["title"])}</h3><p>{esc(c["subtitle"])}</p></figcaption><div class="figure-chart" tabindex="0" role="group" aria-label="Chart; scroll horizontally on narrow screens"><img src="{prefix}{c["id"]}.svg" alt="{esc(c["title"])}" width="600" height="{height}" loading="lazy"/></div>{caption}{table}</figure>'


def card(slug, charts, number):
    s=STORIES[slug]
    return f'<article class="research-study" id="{slug}"><div class="story-copy"><div class="story-index">{number:02d} <span>{esc(s["topic"])}</span></div><h3><a href="projects/{slug}/">{esc(s["title"])}</a></h3><p class="story-context">{esc(s["why"])}</p><div class="story-verdict"><span>What I found</span><h4>{esc(s["finding"])}</h4></div><p class="story-method"><strong>How I tested it.</strong> {esc(s["method"])}</p><p class="story-boundary">{esc(s["boundary"])}</p><div class="story-links"><a href="projects/{slug}/">Read the study →</a><a href="{SPACE}?project={slug}">Explore the evidence ↗</a></div></div>{figure(charts[slug][0],"assets/figures/",False)}</article>'


def replace_region(content,start,end,replacement):
    if start in content:
        return content[:content.index(start)]+start+replacement+end+content[content.index(end)+len(end):]
    raise ValueError(f'Missing generated region {start}')


def build(check=False):
    charts=build_charts()
    outputs={}
    for items in charts.values():
        for c in items:
            outputs[ROOT/'assets/figures'/f'{c["id"]}.svg']=c['svg']+'\n'
            outputs[ROOT/'apps/space/figures'/f'{c["id"]}.svg']=c['svg']+'\n'
    outputs[ROOT/'apps/space/portfolio.css']=(ROOT/'assets/css/portfolio.css').read_text()
    manifest={slug:{**s,'charts':[{k:v for k,v in c.items() if k!='svg'} for c in charts[slug]]} for slug,s in STORIES.items()}
    outputs[ROOT/'assets/data/research_stories.json']=json.dumps(manifest,ensure_ascii=True,indent=2)+'\n'
    home=(ROOT/'index.html').read_text()
    start,end='<!-- RESEARCH STORIES START -->','<!-- RESEARCH STORIES END -->'
    if start not in home:
        begin=home.index('  <section class="case-section"');finish=home.index('  <section class="signal-section"',begin)
        home=home[:begin]+start+end+'\n\n'+home[finish:]
    section='<section class="research-collection" id="research"><div class="container"><div class="collection-heading"><div><div class="section-kicker">Selected research</div><h2>One question.<br>A method. A finding.</h2></div><p>Start with the question that interests you. Each study pairs its conclusion with the evidence behind it.</p></div>'+''.join(card(slug,charts,i+1) for i,slug in enumerate(ORDER))+'</div></section>'
    outputs[ROOT/'index.html']=replace_region(home,start,end,section)
    for slug in ORDER:
        path=ROOT/'projects'/slug/'index.html';page=path.read_text();s=STORIES[slug]
        if '../../assets/css/portfolio.css' not in page:
            page=page.replace('</head>','<link rel="stylesheet" href="../../assets/css/portfolio.css"/></head>')
        page=page.replace('<span class="brand-mark">OQ</span>','<span class="brand-mark">YX</span>').replace('<span class="brand-title">Open Quant &amp; Econ</span>','<span class="brand-title">Yang Xiao</span>')
        ds,de='<!-- STUDY STORY START -->','<!-- STUDY STORY END -->'
        if ds not in page:
            start_index=page.index('<section class="detail-hero">')
            end_index=page.index('<section class="section"><div class="container detail-layout">',start_index)
            page=page[:start_index]+ds+de+page[end_index:]
        study=f'<section class="study-intro container"><div class="breadcrumbs"><a href="../../index.html">Yang Xiao</a><span>{esc(s["topic"])}</span></div><div class="section-kicker">Research question</div><h1>{esc(s["title"])}</h1><p class="study-why">{esc(s["why"])}</p><div class="study-summary"><div><span>01 · Method</span><p>{esc(s["method"])}</p></div><div class="study-conclusion"><span>02 · Conclusion</span><h2>{esc(s["finding"])}</h2><p>{esc(s["takeaway"])}</p></div></div><p class="study-limit"><strong>Scope of the evidence.</strong> {esc(s["boundary"])}</p></section><section class="study-evidence container" id="direct-evidence"><div class="collection-heading"><div><div class="section-kicker">03 · Direct evidence</div><h2>See what supports the finding.</h2></div><a class="text-link" href="{SPACE}?project={slug}">Open interactive Space ↗</a></div><div class="figure-grid">'+''.join(figure(c,'../../assets/figures/') for c in charts[slug])+'</div></section><div class="container technical-heading"><div class="section-kicker">Research notes</div><h2>Design, sources &amp; limitations</h2></div>'
        outputs[path]=replace_region(page,ds,de,study)
    space_path=ROOT/'apps/space/index.html';space=space_path.read_text()
    ss,se='<!-- SPACE EVIDENCE START -->','<!-- SPACE EVIDENCE END -->'
    if ss not in space:
        anchor='<section class="view" id="view-signal" role="tabpanel" aria-labelledby="view-tab-signal" data-view-panel="signal">'
        space=space.replace(anchor,anchor+ss+se)
    panels=''.join(f'<div class="direct-evidence-panel" data-story-panel="{slug}"'+(' hidden' if slug!='casuallab' else '')+'><div class="figure-grid">'+''.join(figure(c,'./figures/') for c in charts[slug])+'</div></div>' for slug in ORDER)
    outputs[space_path]=replace_region(space,ss,se,panels)
    changed=0
    for path,content in outputs.items():
        if path.exists() and path.read_text()==content: continue
        if check: raise SystemExit(f'Stale portfolio artifact: {path.relative_to(ROOT)}')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content);changed+=1
    print(f'research-portfolio-ok projects={len(charts)} figures={sum(map(len,charts.values()))} changed={changed}')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');build(parser.parse_args().check)
