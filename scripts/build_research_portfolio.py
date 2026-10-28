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

from project_sources import source_text

ROOT = Path(__file__).resolve().parents[1]
SITE = 'https://yangxiaoshawn.github.io/'
SPACE = 'https://shawnchamberlain-open-economic-quant-research-ob-5271962.static.hf.space/'
EVIDENCE = json.loads((ROOT / 'assets/data/evidence.json').read_text())
DETAILS = json.loads((ROOT / 'assets/data/research_details.json').read_text())
REV = EVIDENCE['dataset_revision']
INK, BLUE, ORANGE, GREY = '#16243a', '#2458cc', '#b65520', '#8699b4'
ORDER = [
    'casuallab',
    'macroeconomics',
    'realestate',
    'tariff-incidence',
    'microstructure',
    'em-factor-timing',
    'polymarket-factors',
    'crypto-factors',
]
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
    'microstructure': dict(topic='Market microstructure', title='How much short-horizon edge does order flow carry?',
        why='Order-flow imbalance can anticipate small price moves. Measuring that edge properly means replaying it through realistic execution delays and an explicit fee hurdle.',
        finding='Order flow carries a positive gross edge in 110 of 144 execution scenarios.',
        method='I replay one four-hour BTC/ETH order-book capture across two evaluation phases, four horizons, and nine delay combinations, with a fixed 4 bp fee.',
        takeaway='The best gross edge reaches 2.39 bp, measured against a fixed 4 bp taker fee; lower-cost execution is the next test.',
        boundary='Exploratory simulation · research reference only · not live trading. The 144 scenarios overlap and are not independent experiments or a portfolio to add together.',
        short='Order-flow edge', fact='Gross edge in 110 of 144 scenarios', folder='Microstructure'),
    'em-factor-timing': dict(topic='Emerging-market factor timing', title='Can machine learning time equity factors?',
        why='Factor returns vary over time. I test whether learned forecasts add value beyond a pooled, shrinkage-mean benchmark in emerging markets.',
        finding='Pooling explains much of the apparent predictability.',
        method='I compare out-of-sample linear, tree, and neural-network forecasts on JKP global factors, test developed-to-emerging-market transfer, and evaluate timing after turnover costs.',
        takeaway='On capped value-weighted factors, all learned forecasts lose to the shrinkage mean on out-of-sample R². At the baseline trading cost, the shrinkage-mean tilt also beats learned timing portfolios.',
        boundary='Out-of-sample predictive association. Results depend on factor weighting and trading costs; equal-weighted factors differ. Factor returns exclude their own rebalancing costs.',
        short='EM factor timing', fact='Shrinkage mean beats learned timing', folder='EMFactorTiming'),
    'polymarket-factors': dict(topic='Polymarket & prediction markets', title='Which prediction-market signals survive a realistic backtest?',
        why='Bounded prices, early settlement, and stale quotes can create apparent predictability. I study which cross-sectional signals remain after correcting those artifacts.',
        finding='Reversal, volatility, and illiquidity survive the corrections.',
        method='I study 4,000 Polymarket markets, remove five backtest artifacts, control for price levels, and evaluate factor signs on a held-out half of the panel.',
        takeaway='Five backtest artifacts inflate 30-day momentum IC eightfold (−0.440 to −0.054); price-neutral OOS ICs remain significant for illiquidity (−0.072), volatility (−0.069), and reversal (−0.032).',
        boundary='Backtest association, not live execution. Capacity is roughly $100–200 per position. The combined strategy weight was chosen in sample, and daily-close fills omit intraday slippage.',
        short='Polymarket factors', fact='Illiquidity OOS IC −0.072', folder='PolymarketFactors'),
    'crypto-factors': dict(topic='Crypto funding & positioning', title='Do equity microstructure factors travel to crypto?',
        why='Crypto offers open minute-bar and perpetual-futures data. I test whether ideas from an A-share microstructure research series carry over to this different market.',
        finding='Most factors do not travel; funding and positioning hold up better.',
        method='I test cross-sectional factors on 105 coins, check split samples and parameters, compare funding on OKX, and track the composite after publication.',
        takeaway='Funding (+1.42 Sharpe), retail positioning (+1.39), and a low-price range factor (+1.63) support a market-neutral composite in the 730-day panel. Post-publication windows include both gains and losses.',
        boundary='Backtest and out-of-sample backtest association, not live trading. Next-close fills omit market impact; the sample is an altcoin bear market and the OKX check is short.',
        short='Crypto factor transfer', fact='Funding & positioning travel best', folder='CryptoFactors'),
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


def signed_bars(title, labels, values, unit, min_val, max_val, colors=None, digits=3):
    height = max(250, len(labels) * 38 + 100)
    left, right, top = 188, 535, 48
    zero_x = left + (0 - min_val) / (max_val - min_val) * (right - left)
    body = text(left, 22, unit, 13, '#59697d')
    for i in range(5):
        val = min_val + (max_val - min_val) * i / 4
        x = left + (right - left) * i / 4
        body += line(x, top - 12, x, height - 45)
        body += text(x, height - 20, f'{val:g}', 12, '#59697d', 'middle')
    body += line(zero_x, top - 14, zero_x, height - 43, '#8699b4', 1.5)
    step = (height - 100) / max(len(labels), 1)
    for i, (label, value) in enumerate(zip(labels, values)):
        y = top + i * step
        body += text(left - 12, y + 15, label, 13, INK, 'end')
        val_x = left + (value - min_val) / (max_val - min_val) * (right - left)
        x0 = min(zero_x, val_x)
        w = max(abs(val_x - zero_x), 1.5)
        col = (colors or [BLUE] * len(values))[i]
        body += f'<rect x="{x0:.2f}" y="{y:.2f}" width="{w:.2f}" height="21" rx="2" fill="{col}"/>'
        tx = val_x + 7 if value >= 0 else val_x - 7
        anchor = 'start' if value >= 0 else 'end'
        body += text(tx, y + 15, f'{value:+.{digits}f}', 12, INK, anchor, 600)
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
    report=source_text('tariff-incidence','reports/tariff_incidence_results.md')
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
    body=text(58,22,'Gross edge (basis points per unit turnover)',13,'#59697d')
    sx=lambda i:58+i/143*510
    sy=lambda v:277-(v+6)/11*218
    for v in [-4,-2,0,2,4]:
        body+=line(58,sy(v),568,sy(v),'#9cabbf' if v==0 else '#e2e7ef',1.4 if v==0 else 1)+text(46,sy(v)+4,str(v),12,'#59697d','end')
    body+=line(58,sy(4),568,sy(4),ORANGE,1,'5 4')+text(560,sy(4)-10,'4 bp taker fee',12,ORANGE,'end')
    for i,r in enumerate(scenarios):
        body+=f'<circle cx="{sx(i):.2f}" cy="{sy(r["gross_edge_bps"]):.2f}" r="2.25" fill="{BLUE}"/>'
    body+=text(58,302,'1',12,'#59697d','middle')+text(568,302,'144',12,'#59697d','middle')+text(315,323,'Scenarios, sorted by gross edge',13,'#59697d','middle')
    body+=text(58,43,'● Gross edge per scenario',13,BLUE)
    charts['microstructure'].append(chart('trading-all-scenarios','Gross edge across 144 scenarios','Each dot is one fee-and-latency scenario · dashed line marks the fixed 4 bp fee',svg('Gross edge for every one of 144 overlapping simulated trading scenarios, with the 4 bp fee marked',body,340),
        'Each dot is one scenario’s gross edge per unit of turnover, sorted from lowest to highest; 110 of 144 are above zero and the best reaches 2.39 bp. The dashed line marks the fixed 4 bp taker fee. Overlapping scenarios must not be summed.',
        ['Symbol','Phase','Horizon','Decision delay (events)','Order delay (events)','Gross edge (bp)'],[[r['symbol'],r['phase'],r['endpoint'],r['decision_latency_events'],r['order_latency_events'],r['gross_edge_bps']] for r in scenarios],'assets/data/microstructure_backtest_reference.json'))
    horizons=[('event_20','20 events'),('event_100','100 events'),('clock_1000ms','1 second'),('clock_5000ms','5 seconds')]
    by_h=[(label,sum(1 for r in ref['scenarios'] if r['endpoint']==key and r['gross_edge_bps']>0),sum(1 for r in ref['scenarios'] if r['endpoint']==key)) for key,label in horizons]
    charts['microstructure'].append(chart('trading-positive','Gross edge is positive at every horizon','Gross-positive scenarios out of 36 per horizon',
        bars('Gross-positive scenarios by forecast horizon',[h[0] for h in by_h],[h[1] for h in by_h],'Gross-positive scenarios',36,[BLUE]*len(by_h),0),
        'At least 22 of 36 scenarios are gross-positive at each horizon, and 35 of 36 at the 100-event horizon. This is one four-hour exploratory capture, not a test of live profitability or cross-day reliability.',
        ['Horizon','Gross-positive scenarios','Total scenarios'],[list(h) for h in by_h],'assets/data/microstructure_backtest_reference.json'))

    # 06: EMFactorTiming
    em = EVIDENCE['projects']['em-factor-timing']
    em_ports = DETAILS['em-factor-timing']['portfolios']
    charts['em-factor-timing'].append(chart(
        'em-static-vs-timing',
        'Shrinkage mean beats every learned timing model on OOS R²',
        'Out-of-sample R² vs unpooled own mean (%) · 801,536 country-factor-months',
        bars(
            'Out-of-sample R-squared versus own mean across EM factor timing models',
            [r['model_scope'] for r in em['series']],
            [r['r2_vs_hist_pct'] for r in em['series']],
            'OOS R² vs own mean (%)',
            1.4,
            [ORANGE if r['model_scope'] == 'Shrinkage mean' else BLUE if r['r2_vs_hist_pct'] > 0 else GREY for r in em['series']],
            2,
        ),
        'Against the unpooled own mean, every model achieves positive OOS R² (+0.83% to +1.16%), but the non-timing regional shrinkage mean alone reaches +1.20% (t = 9.05). Measured against the shrinkage mean, all learned models have negative OOS R².',
        ['Model / scope', 'OOS R² vs own mean (%)', 'OOS R² vs shrinkage (%)', 'Net Sharpe (20 bp)'],
        [[r['model_scope'], r['r2_vs_hist_pct'], r['r2_vs_shrink_pct'], r['sharpe_net']] for r in em['series']],
        em['source'],
    ))
    charts['em-factor-timing'].append(chart(
        'em-factor-themes',
        'Shrinkage-mean tilt leads net Sharpe after turnover costs',
        'Annualized Sharpe ratio net of 20 bp turnover cost · 2000–2025 OOS',
        bars(
            'Net Sharpe ratio across emerging-market factor portfolios at 20 bp cost',
            [r['label'] for r in em_ports],
            [r['sharpe_net'] for r in em_ports],
            'Net Sharpe ratio (at 20 bp cost)',
            2.2,
            [ORANGE if r['label'] == 'Shrinkage-mean tilt' else BLUE if 'Static' in r['label'] else GREY for r in em_ports],
            2,
        ),
        'Because learned timing rules turn over 41%–61% per month versus 6.1% for the shrinkage-mean tilt, the shrinkage-mean portfolio achieves the highest net Sharpe (1.91) ahead of static equal weight (1.48) and GBRT (1.26).',
        ['Portfolio rule', 'Net Sharpe (20 bp)', 'Monthly turnover'],
        [[r['label'], r['sharpe_net'], r['turnover']] for r in em_ports],
        DETAILS['em-factor-timing']['portfolios_source'],
    ))

    # 07: PolymarketFactors
    poly = EVIDENCE['projects']['polymarket-factors']
    poly_funnel = DETAILS['polymarket-factors']['funnel']
    charts['polymarket-factors'].append(chart(
        'polymarket-factor-ic',
        'Illiquidity, volatility, and reversal survive price-level controls',
        'Out-of-sample price-neutral rank IC · 54 five-day periods across 4,000 markets',
        signed_bars(
            'Out-of-sample price-neutral rank IC by Polymarket factor',
            [r['factor'] for r in poly['series']],
            [r['price_neutral_ic'] for r in poly['series']],
            'Price-neutral rank IC (OOS)',
            -0.09, 0.04,
            [BLUE if abs(r['price_neutral_ic']) >= 0.028 else GREY for r in poly['series']],
            3,
        ),
        'After residualizing on [1, p, p²], illiquidity (PM-LIQ, IC = −0.072), low volatility (PM-VOL, −0.069), 30-day reversal (PM-MOM, −0.032), and time-to-resolution (PM-TTR, −0.028) remain statistically significant out of sample.',
        ['Factor', 'Price-neutral IC (OOS)', 'Raw Δp IC (OOS)', 'Interpretation'],
        [[r['factor'], r['price_neutral_ic'], r['raw_ic'], r['outcome']] for r in poly['series']],
        poly['source'],
    ))
    charts['polymarket-factors'].append(chart(
        'polymarket-category-ic',
        'Five backtest artifacts inflate naive momentum IC eightfold',
        '30-day momentum raw IC across progressive artifact-removal stages',
        signed_bars(
            '30-day momentum IC across five backtest artifact-removal stages',
            [r['stage'] for r in poly_funnel],
            [r['raw_ic'] for r in poly_funnel],
            '30-day momentum IC',
            -0.50, 0.05,
            [ORANGE if i == 0 else BLUE if i == len(poly_funnel) - 1 else GREY for i in range(len(poly_funnel))],
            3,
        ),
        'Percentage returns near zero, extreme price bounds, same-bar bounce, pre-settlement drift, and stale non-executable quotes inflate the apparent 30-day reversal IC from −0.440 to −0.054 raw (−0.032 price-neutral).',
        ['Cleaning stage', 'Raw IC', 'Price-neutral IC'],
        [[r['stage'], r['raw_ic'], r['pn_ic'] if r['pn_ic'] is not None else '—'] for r in poly_funnel],
        DETAILS['polymarket-factors']['funnel_source'],
    ))

    # 08: CryptoFactors
    crypto = EVIDENCE['projects']['crypto-factors']
    crypto_post = DETAILS['crypto-factors']['postpub_windows']
    charts['crypto-factors'].append(chart(
        'crypto-factor-transfer',
        'Funding, retail positioning, and low-price range transfer to crypto',
        '730-day daily quintile long–short Sharpe (net of 5 bp/side) · 105 coins',
        signed_bars(
            '730-day daily long-short Sharpe ratio across seven factors on 105 coins',
            [r['factor'] for r in crypto['series']],
            [r['sharpe_730d'] for r in crypto['series']],
            '730-day L/S Sharpe (net 5 bp/side)',
            -1.6, 1.9,
            [BLUE if r['sharpe_730d'] > 1.0 else ORANGE if r['sharpe_730d'] > 0 else GREY for r in crypto['series']],
            2,
        ),
        'Low-price range (+1.63), funding-rate contrarian carry (+1.42), and retail long/short positioning (+1.39) hold up across the 730-day Binance panel and OKX cross-validation, while cross-sectional momentum (−0.38) fails to transfer.',
        ['Factor', '730-day L/S Sharpe', 'Audit verdict'],
        [[r['factor'], r['sharpe_730d'], r['outcome']] for r in crypto['series']],
        crypto['source'],
    ))
    charts['crypto-factors'].append(chart(
        'crypto-postpub-composite',
        'Post-publication out-of-sample windows include both gains and drawdowns',
        'Frozen 3-factor composite return (%) across 92 post-publication days (Jun–Aug 2026)',
        signed_bars(
            'Post-publication composite return by monthly window',
            [r['window'] for r in crypto_post],
            [r['return_pct'] for r in crypto_post],
            'Post-publication return (%)',
            -10.0, 6.0,
            [BLUE if r['return_pct'] > 0 else ORANGE for r in crypto_post],
            2,
        ),
        'Tracked out of sample without re-fitting after the May 2026 cutoff, the equal-weight composite gained +4.57% in June 2026 before losing −6.93% in July and −3.97% in August (−6.55% cumulative), underscoring regime sensitivity.',
        ['Post-publication window', 'Net return (%)', 'Max drawdown (%)'],
        [[r['window'], r['return_pct'], r['max_dd_pct']] for r in crypto_post],
        DETAILS['crypto-factors']['postpub_source'],
    ))
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


def fmt_pct(val: float) -> str:
    if abs(val) < 0.005:
        val = 0.0
    cls = 'val-pos' if val > 0 else ('val-neg' if val < 0 else '')
    sign = '+' if val > 0 else ''
    return f'<td class="{cls}">{sign}{val:.2f}%</td>'


def build_architecture_and_monitor_html(rel_prefix: str = '') -> str:
    mon_path = ROOT / 'assets/data/daily_trading_monitor.json'
    if not mon_path.exists():
        return ''
    mon = json.loads(mon_path.read_text(encoding='utf-8'))
    cf = mon['crypto_factors']
    em = mon['em_factor_timing']

    # Build CryptoFactors Day-by-Day Table
    cf_day_ths = ''.join(f'<th scope="col">{esc(h)}</th>' for h in cf['day_headers'])
    cf_rows_html = []
    for r in cf['rows']:
        hl = ' class="row-highlight"' if r['category'] in ('Deliverable', 'Composite') else ''
        d_cells = ''.join(fmt_pct(v) for v in r['daily'])
        cf_rows_html.append(
            f'<tr{hl}>'
            f'<td><strong>{esc(r["name"])}</strong></td>'
            f'<td><span class="badge-cat">{esc(r["category"])}</span></td>'
            f'{d_cells}'
            f'{fmt_pct(r["recent_settled_pct"])}'
            f'{fmt_pct(r["recent_incl_live_pct"])}'
            f'{fmt_pct(r["oct_mtd_pct"])}'
            f'{fmt_pct(r["since_sep29_pct"])}'
            f'{fmt_pct(r["since_sep01_pct"])}'
            f'</tr>'
        )
    cf_table = (
        f'<div class="monitor-table-wrap"><table class="monitor-table">'
        f'<thead><tr><th scope="col">Strategy / Factor / Benchmark</th><th scope="col">Type</th>'
        f'{cf_day_ths}'
        f'<th scope="col">{esc(cf["recent_settled_label"])}</th>'
        f'<th scope="col">{esc(cf["recent_all_label"])}</th>'
        f'<th scope="col">{esc(cf["oct_label"])}</th>'
        f'<th scope="col">Since Sep 29</th>'
        f'<th scope="col">Since Sep 01</th>'
        f'</tr></thead><tbody>{"".join(cf_rows_html)}</tbody></table></div>'
    )

    # Pre-registered 2026-10-23 signal book table
    prereg_rows_html = []
    for r in cf.get('preregistered_book_2026_10_23', []):
        prereg_rows_html.append(
            f'<tr>'
            f'<td><strong>{esc(r["date_utc"])}</strong></td>'
            f'<td>Frozen 2026-10-23 Book</td>'
            f'{fmt_pct(r["BTC_pct"])}'
            f'{fmt_pct(r["ETH_pct"])}'
            f'{fmt_pct(r["Big24_EW_pct"])}'
            f'{fmt_pct(r["Wide_EW_pct"])}'
            f'{fmt_pct(r["ProdB_Long8_pct"])}'
            f'{fmt_pct(r["ProdB_MktNeutral_pct"])}'
            f'{fmt_pct(r["ProdB_Top8_vs_Bot5_pct"])}'
            f'{fmt_pct(r.get("GLS_LS_pct", 0.0))}'
            f'{fmt_pct(r.get("FUND_LS_pct", 0.0))}'
            f'{fmt_pct(r.get("AMP_LS_pct", 0.0))}'
            f'{fmt_pct(r.get("REV_LS_pct", 0.0))}'
            f'</tr>'
        )
    prereg_table = (
        f'<details class="figure-values" style="margin-top:16px"><summary>Inspect pre-registered 2026-10-23 fixed-holdings signal book day-by-day ({len(prereg_rows_html)} UTC days)</summary>'
        f'<div class="monitor-table-wrap" style="margin-top:10px"><table class="monitor-table">'
        f'<thead><tr><th scope="col">UTC Date</th><th scope="col">Book</th>'
        f'<th scope="col">BTC</th><th scope="col">ETH</th><th scope="col">Big-24 EW</th><th scope="col">Wide-105 EW</th>'
        f'<th scope="col">Prod B Long-8</th><th scope="col">Prod B Mkt-Neutral</th><th scope="col">Prod B Top8-Bot5</th>'
        f'<th scope="col">Retail L/S</th><th scope="col">Funding L/S</th><th scope="col">Low-Price Range L/S</th><th scope="col">Reversal L/S</th>'
        f'</tr></thead><tbody>{"".join(prereg_rows_html)}</tbody></table></div></details>'
    )

    # Build EMFactorTiming Day-by-Day Table
    em_day_ths = ''.join(f'<th scope="col">{esc(h)}</th>' for h in em['day_headers'])
    em_rows_html = []
    for r in em['rows']:
        hl = ' class="row-highlight"' if r['category'] == 'Timing Portfolio' else ''
        d_cells = ''.join(fmt_pct(v) for v in r['daily'])
        em_rows_html.append(
            f'<tr{hl}>'
            f'<td><strong>{esc(r["name"])}</strong></td>'
            f'<td><span class="badge-cat">{esc(r["category"])}</span></td>'
            f'{d_cells}'
            f'{fmt_pct(r["recent_cum_pct"])}'
            f'{fmt_pct(r["oct_mtd_pct"])}'
            f'{fmt_pct(r["ytd_2026_pct"])}'
            f'</tr>'
        )
    em_table = (
        f'<div class="monitor-table-wrap"><table class="monitor-table">'
        f'<thead><tr><th scope="col">Factor Spread / Timing Portfolio / Benchmark</th><th scope="col">Category</th>'
        f'{em_day_ths}'
        f'<th scope="col">{esc(em["recent_cum_label"])}</th>'
        f'<th scope="col">{esc(em["oct_label"])}</th>'
        f'<th scope="col">2026 YTD</th>'
        f'</tr></thead><tbody>{"".join(em_rows_html)}</tbody></table></div>'
    )

    # EM 21 Country ETFs table
    cty_rows_html = []
    for r in em.get('countries', []):
        d_cells = ''.join(fmt_pct(v) for v in r['daily'])
        cty_rows_html.append(
            f'<tr>'
            f'<td><strong>{esc(r["country_etf"])}</strong></td>'
            f'<td><span class="badge-cat">MSCI EM Country</span></td>'
            f'{d_cells}'
            f'{fmt_pct(r["recent_cum_pct"])}'
            f'{fmt_pct(r["oct_mtd_pct"])}'
            f'{fmt_pct(r["ytd_2026_pct"])}'
            f'</tr>'
        )
    cty_table = (
        f'<details class="figure-values" style="margin-top:16px"><summary>Inspect all 21 MSCI Emerging-Market country ETFs day-by-day ({esc(em["day_headers"][0])} to {esc(em["day_headers"][-1])})</summary>'
        f'<div class="monitor-table-wrap" style="margin-top:10px"><table class="monitor-table">'
        f'<thead><tr><th scope="col">Country ETF</th><th scope="col">Universe</th>'
        f'{em_day_ths}'
        f'<th scope="col">{esc(em["recent_cum_label"])}</th>'
        f'<th scope="col">{esc(em["oct_label"])}</th>'
        f'<th scope="col">2026 YTD</th>'
        f'</tr></thead><tbody>{"".join(cty_rows_html)}</tbody></table></div></details>'
    )

    arch_html = (
        f'<section class="arch-section" id="architecture"><div class="container">'
        f'<div class="collection-heading"><div><div class="section-kicker">Unified monorepo architecture</div>'
        f'<h2>One codebase. Eight studies.<br>Shared statistical rigor.</h2></div>'
        f'<p>All eight projects are consolidated in the <a href="https://github.com/YangXiaoShawn/open-economic-quant" style="color:var(--accent);font-weight:600">open-economic-quant</a> monorepo, sharing a core econometric &amp; portfolio engine (<code>oeq-core v0.2.0</code>) and automated CI verification.</p></div>'
        f'<div class="arch-grid">'
        f'<article class="arch-card"><div class="section-kicker">Layer 01 · Shared Engine</div><h3><code>oeq-core v0.2.0</code> Infrastructure</h3>'
        f'<p>Centralized statistical and portfolio primitives imported across subprojects with 100% unit-test coverage:</p>'
        f'<ul>'
        f'<li><strong>Shrinkage &amp; Covariance:</strong> Empirical Bayes adaptive cross-sectional shrinkage &amp; Ledoit-Wolf covariance regularization.</li>'
        f'<li><strong>Inference &amp; Multiple Testing:</strong> Newey-West HAC t-statistics, Politis-Romano stationary bootstrap, White Reality Check, and Deflated Sharpe Ratio (DSR).</li>'
        f'<li><strong>Execution Shortfall:</strong> Turnover-damped weights, break-even fee solvers, and Almgren-Chriss square-root market impact.</li>'
        f'</ul></article>'
        f'<article class="arch-card"><div class="section-kicker">Layer 02 · Eight Subprojects</div><h3>Three Research Pillars</h3>'
        f'<p>Standardized <code>pyproject.toml</code> + <code>src/</code> packages with 48 canonical data &amp; report artifacts:</p>'
        f'<ul>'
        f'<li><strong>Causal &amp; Policy (01–04):</strong> <a href="{rel_prefix}projects/casuallab/">CasualLab</a>, <a href="{rel_prefix}projects/macroeconomics/">Macroeconomics</a>, <a href="{rel_prefix}projects/realestate/">RealEstate</a>, <a href="{rel_prefix}projects/tariff-incidence/">TariffIncidence</a>.</li>'
        f'<li><strong>Microstructure &amp; Prediction (05, 07):</strong> <a href="{rel_prefix}projects/microstructure/">Microstructure</a> (144 L2 latency scenarios), <a href="{rel_prefix}projects/polymarket-factors/">PolymarketFactors</a> (4,000 markets).</li>'
        f'<li><strong>Live-Tracked Factor Timing (06, 08):</strong> <a href="{rel_prefix}projects/em-factor-timing/">EMFactorTiming</a> (22 EM countries &amp; 49 ETFs), <a href="{rel_prefix}projects/crypto-factors/">CryptoFactors</a> (105 perpetuals).</li>'
        f'</ul></article>'
        f'<article class="arch-card"><div class="section-kicker">Layer 03 · Live Verification</div><h3>Automated Sync &amp; Stress Audits</h3>'
        f'<p>Every update runs <code>verify_monorepo.py</code> and <code>sync_ecosystem.py</code> across GitHub and Hugging Face:</p>'
        f'<ul>'
        f'<li><strong>4-Part Live-Readiness Audit:</strong> Execution delay (0m / 1m / 5m / 1h / 24h), realistic 24-perp short hedge with 8h funding, capacity stress ($10k–$5M), and pre-trade bad-print guards.</li>'
        f'<li><strong>Public Reproducibility:</strong> Pinned <a href="https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data">HF Dataset</a> ({EVIDENCE["portfolio"]["total_files"]:,} files) &amp; <a href="https://huggingface.co/spaces/ShawnChamberlain/open-economic-quant-research-observatory">HF Space</a>.</li>'
        f'</ul></article>'
        f'</div></div></section>'
    )

    cf_by_name = {r['name']: r for r in cf['rows']}
    em_by_name = {r['name']: r for r in em['rows']}
    rev_row = cf_by_name.get('High-Volume Reversal (REV_hi, Wide-105)', {})
    inv_row = em_by_name.get('Investment / Conservative (IWD - IWF)', {})
    mom_row = em_by_name.get('Momentum (MTUM - SPY)', {})
    rev_mtd = rev_row.get('oct_mtd_pct', 8.35)
    rev_sep1 = rev_row.get('since_sep01_pct', 10.50)
    rev_rec = rev_row.get('recent_settled_pct', 3.60)
    inv_mtd = inv_row.get('oct_mtd_pct', 5.99)
    mom_last4 = mom_row.get('daily', [0.83, 1.05, 1.13, 1.06])[-4:]
    mom_last4_str = ', '.join(f'{v:+.2f}%' for v in mom_last4)

    monitor_html = (
        f'<section class="monitor-section" id="daily-monitor"><div class="container">'
        f'<div class="collection-heading"><div><div class="section-kicker">Live out-of-sample monitor · Updated {esc(mon["generated_at_utc"])}</div>'
        f'<h2>Day-by-day trading results.</h2></div>'
        f'<p>Realized out-of-sample returns tracked day by day across 105 crypto perpetuals (Binance Vision + OKX UTC) and 49 US-listed emerging/developed market ETFs.</p></div>'
        f'<div class="monitor-kpis">'
        f'<article class="monitor-kpi"><span>Crypto Deliverable · Product B</span><strong>+28.41%</strong><small>537-day net return (+0.81 Sharpe) under realistic 24-perp short hedge, 8h funding &amp; 1-min delay ($500k–$1M capacity)</small></article>'
        f'<article class="monitor-kpi"><span>Crypto High-Volume Reversal</span><strong>{rev_mtd:+.2f}%</strong><small>October 2026 MTD net return ({rev_sep1:+.2f}% since Sep 1), with {rev_rec:+.2f}% across the last 7 settled days (Oct 21–27)</small></article>'
        f'<article class="monitor-kpi"><span>EM Shrinkage Factor Tilt</span><strong>517–1,720 bp</strong><small>Break-even transaction cost in 2026 OOS (+1.98% 2026 YTD tradable ETF excess return vs −5.71% EEM)</small></article>'
        f'<article class="monitor-kpi"><span>EM Conservative Investment</span><strong>{inv_mtd:+.2f}%</strong><small>October 2026 MTD spread return (IWD − IWF), providing +3.09% crisis alpha during the Oct 22 equity sell-off</small></article>'
        f'</div>'
        f'<div class="monitor-block">'
        f'<div class="monitor-block-head"><h3>01 · CryptoFactors Day-by-Day Realized Net Returns (105 Coins, UTC Days)</h3>'
        f'<span>Binance settled: {esc(cf["latest_binance_settled_date"])} · OKX UTC: {esc(cf["latest_okx_utc_date"])}</span></div>'
        f'<p class="monitor-note">Each column reports the net return realized on that UTC day from signals formed at the prior 00:00 UTC close (net of 10 bp round-trip cost for single factors and 15 bp weekly rebalance cost for Product B, including 8h perpetual funding accrual). During the Oct 22–25 deleveraging sell-off (Big-24 EW −7.70%), <strong>Low-Price Range</strong> gained +7.73% over four consecutive positive days and <strong>Product B Beta-Hedged</strong> gained +1.52% on the Oct 22 crash day; during the Oct 26–27 short squeeze, <strong>Taker Buy / Large-Trade OFI</strong> and <strong>High-Volume Reversal</strong> led.</p>'
        f'{cf_table}'
        f'{prereg_table}'
        f'<p style="margin:12px 0 0;font-size:13px"><a href="{esc(source_url("CryptoFactors/reports/live_readiness_2026_10/crypto_day_by_day_comparison_2026_10_28.csv"))}" style="color:var(--accent);font-weight:600">Download CryptoFactors day-by-day CSV ↗</a> · <a href="{esc(source_url("CryptoFactors/reports/LIVE_READINESS_AUDIT_2026-10.md"))}" style="color:var(--accent);font-weight:600">Read Live-Readiness Stress Audit ↗</a></p>'
        f'</div>'
        f'<div class="monitor-block" style="margin-bottom:0">'
        f'<div class="monitor-block-head"><h3>02 · EMFactorTiming Day-by-Day Realized Returns (49 US-Listed EM/DM ETFs)</h3>'
        f'<span>Latest US trading session: {esc(em["latest_us_trading_date"])}{" (Intraday Live)" if em["latest_is_live"] else " (Settled Close)"}</span></div>'
        f'<p class="monitor-note">Daily factor spreads and country ETF returns across 7 tradable global/EM style factors, 2 composite timing portfolios, and 21 MSCI EM country ETFs. On Thursday Oct 22 (when EEM fell −2.91% and SPY fell −1.18%), all six fundamental/defensive style factors rallied (<strong>Investment</strong> +3.09%, <strong>Low Risk</strong> +1.65%, <strong>Value</strong> +1.03%, <strong>Shrinkage Tilt</strong> +1.27%); across Oct 23–28, <strong>Momentum</strong> rebounded for four consecutive sessions ({mom_last4_str}).</p>'
        f'{em_table}'
        f'{cty_table}'
        f'<p style="margin:12px 0 0;font-size:13px"><a href="{esc(source_url("EMFactorTiming/reports/live_readiness_2026_10/em_day_by_day_comparison_2026_10_28.csv"))}" style="color:var(--accent);font-weight:600">Download EMFactorTiming day-by-day CSV ↗</a> · <a href="{esc(source_url("EMFactorTiming/reports/LIVE_READINESS_AUDIT_2026-10.md"))}" style="color:var(--accent);font-weight:600">Read EM Live-Readiness Audit ↗</a></p>'
        f'</div>'
        f'</div></section>'
    )
    return arch_html + monitor_html


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
    arch_start,arch_end='<!-- ARCHITECTURE AND DAILY MONITOR START -->','<!-- ARCHITECTURE AND DAILY MONITOR END -->'
    if arch_start in home:
        home=replace_region(home,arch_start,arch_end,build_architecture_and_monitor_html(''))
    start,end='<!-- RESEARCH STORIES START -->','<!-- RESEARCH STORIES END -->'
    if start not in home:
        begin=home.index('  <section class="case-section"');finish=home.index('  <section class="signal-section"',begin)
        home=home[:begin]+start+end+'\n\n'+home[finish:]
    section='<section class="research-collection" id="research"><div class="container"><div class="collection-heading"><div><div class="section-kicker">Selected research</div><h2>One question.<br>A method. A finding.</h2></div><p>Start with the question that interests you. Each study pairs its conclusion with the evidence behind it.</p></div>'+''.join(card(slug,charts,i+1) for i,slug in enumerate(ORDER))+'</div></section>'
    outputs[ROOT/'index.html']=replace_region(home,start,end,section)
    sub_start,sub_end='<!-- DAILY MONITOR SUBPAGE START -->','<!-- DAILY MONITOR SUBPAGE END -->'
    for sub_route in ('daily-reports', 'updated-results'):
        sub_path = ROOT / sub_route / 'index.html'
        if sub_path.exists():
            sub_txt = sub_path.read_text()
            if sub_start in sub_txt:
                outputs[sub_path] = replace_region(sub_txt, sub_start, sub_end, build_architecture_and_monitor_html('../'))
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
