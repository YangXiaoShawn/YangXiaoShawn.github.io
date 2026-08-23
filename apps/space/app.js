(() => {
  'use strict';

  const REPO = 'ShawnChamberlain/open-economic-quant-research-data';
  const ORDER = ['casuallab', 'macroeconomics', 'realestate', 'tariff-incidence', 'microstructure'];
  const VIEWS = ['signal', 'portfolio', 'files', 'notes'];
  const META = {
    casuallab: { folder: 'CasualLab', accent: 'teal', field: 'Causal inference', portfolioTitle: 'Experiment design under spillovers', portfolioValue: '19.7M', portfolioLabel: 'NYC TLC records processed and quality-checked', portfolioSummary: 'Built an estimand-first marketplace lab that benchmarks experiment designs and budget-constrained policies against known causal truth.', page: 'https://yangxiaoshawn.github.io/projects/casuallab/', data: 'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/CasualLab', source: 'https://github.com/YangXiaoShawn/open-economic-quant-casuallab' },
    macroeconomics: { folder: 'Macroeconomics', accent: 'blue', field: 'Macroeconomics', portfolioTitle: 'Real-time forecasting without future-data leakage', portfolioValue: '626K', portfolioLabel: 'official archive rows parsed and hashed', portfolioSummary: 'Built a vintage-aware nowcasting engine that reconstructs the information actually available at each historical forecast date.', page: 'https://yangxiaoshawn.github.io/projects/macroeconomics/', data: 'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/Macroeconomics', source: 'https://github.com/YangXiaoShawn/open-economic-quant-macroeconomics' },
    realestate: { folder: 'RealEstate', accent: 'amber', field: 'Housing economics', portfolioTitle: 'Point-in-time mortgage lock-in analytics', portfolioValue: '8', portfolioLabel: 'distinct lock-in measures designed', portfolioSummary: 'Built a point-in-time housing-finance system linking mortgage rate gaps to exits, local activity, prices, and construction.', page: 'https://yangxiaoshawn.github.io/projects/realestate/', data: 'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/RealEstate', source: 'https://github.com/YangXiaoShawn/open-economic-quant-realestate' },
    'tariff-incidence': { folder: 'TariffIncidence', accent: 'green', field: 'International trade', portfolioTitle: 'A point-in-time tariff policy engine', portfolioValue: '12,587', portfolioLabel: 'tariff records parsed from legal notices', portfolioSummary: 'Built a Section 301 policy engine that traces legal notices into incidence, sourcing, and industry-exposure analysis.', page: 'https://yangxiaoshawn.github.io/projects/tariff-incidence/', data: 'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/TariffIncidence', source: 'https://github.com/YangXiaoShawn/open-economic-quant-tariff-incidence' },
    microstructure: { folder: 'Microstructure', accent: 'violet', field: 'Market microstructure', portfolioTitle: 'Signal-to-execution stress testing', portfolioValue: '144', portfolioLabel: 'fee- and latency-aware scenarios audited', portfolioSummary: 'Built a leakage-safe framework that stress-tests apparent edge against fees, latency, fills, inventory, and drawdown.', page: 'https://yangxiaoshawn.github.io/projects/microstructure/', data: 'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/Microstructure', source: 'https://github.com/YangXiaoShawn/open-economic-quant-microstructure' }
  };
  const COLORS = { code: '#6ee7d8', data: '#8eb8ff', reports: '#ffca6a', tests: '#7fe4aa' };
  const params = new URLSearchParams(location.search);
  let activeProject = ORDER.includes(params.get('project')) ? params.get('project') : 'casuallab';
  let activeMetric = params.get('metric');
  let activeView = VIEWS.includes(params.get('view')) ? params.get('view') : 'signal';
  let activeFilter = ['all', 'code', 'data', 'reports', 'tests'].includes(params.get('filter')) ? params.get('filter') : 'all';
  let evidence = null;
  let backtestReference = null;
  let rows = [];
  const cache = {};
  const categoryLabel = (category) => activeProject === 'microstructure' && category === 'data' ? 'data paths' : category;

  const one = (selector) => document.querySelector(selector);
  const all = (selector) => [...document.querySelectorAll(selector)];
  const escapeHTML = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
  const compact = (value, digits = 1) => new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: digits }).format(value);
  const signed = (value, digits = 3) => `${value > 0 ? '+' : ''}${Number(value).toFixed(digits)}`;
  const byteSize = (value) => Number.isFinite(value) ? `${new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(value)}B` : '—';
  const datasetFileURL = (source, revision) => {
    const path = String(source).split('/').map(encodeURIComponent).join('/');
    return `https://huggingface.co/datasets/${REPO}/blob/${encodeURIComponent(revision)}/${path}`;
  };

  const formatValue = (value, metric) => {
    if (!Number.isFinite(Number(value))) return '—';
    const numeric = Number(value);
    if (metric.unit === 'trips') return compact(numeric, 2);
    if (metric.unit === 'USD') return `$${numeric.toFixed(2)}`;
    if (metric.unit === 'USDT') return `${numeric < 0 ? '−' : numeric > 0 ? '+' : ''}$${Math.abs(numeric).toFixed(2)}`;
    if (metric.unit === 'bp / turnover') return `${numeric > 0 ? '+' : ''}${numeric.toFixed(2)} bp`;
    if (metric.unit === '%') return `${numeric.toFixed(metric.id === 'hazard' ? 3 : 2)}%`;
    if (['cells', 'rows', 'warnings'].includes(metric.unit)) return Math.round(numeric).toLocaleString('en-US');
    if (metric.unit === 'log points') return signed(numeric);
    if (metric.unit === 'effect units') return numeric.toFixed(4);
    return numeric.toLocaleString('en-US');
  };

  const formatAxis = (value, metric) => {
    const numeric = Number(value);
    if (['trips', 'cells', 'rows', 'warnings'].includes(metric.unit)) return compact(numeric, 1);
    if (metric.unit === 'USD') return `$${numeric.toFixed(0)}`;
    if (metric.unit === 'USDT') return `${numeric < 0 ? '−' : ''}$${Math.abs(numeric).toFixed(0)}`;
    if (metric.unit === 'bp / turnover') return `${numeric.toFixed(1)} bp`;
    if (metric.unit === '%') return `${numeric.toFixed(numeric >= 10 ? 0 : 1)}%`;
    if (metric.unit === 'log points') return signed(numeric, 2);
    if (metric.unit === 'effect units') return numeric.toFixed(3);
    return numeric.toFixed(1);
  };

  const xDescriptor = (slug, row) => {
    if (slug === 'casuallab') return { numeric: null, label: row.model };
    if (slug === 'macroeconomics') return { numeric: null, label: row.mode };
    if (slug === 'realestate') return { numeric: row.mean_gap, label: `${row.mean_gap > 0 ? '+' : ''}${row.mean_gap.toFixed(2)} pp` };
    if (slug === 'microstructure') return { numeric: null, label: row.stage };
    return { numeric: null, label: row.window };
  };

  const context = (slug, row) => {
    if (slug === 'macroeconomics') return `${row.feature_cells.toLocaleString('en-US')} feature cells`;
    if (slug === 'realestate') return `${row.bucket} · ${row.events.toLocaleString('en-US')} events`;
    if (slug === 'tariff-incidence') return `N = ${row.n.toLocaleString('en-US')}`;
    if (slug === 'microstructure') return row.outcome;
    if (slug === 'casuallab') return row.outcome;
    return 'Published research observation';
  };

  const category = (path) => {
    const value = path.toLowerCase();
    if (value.includes('/tests/') || value.endsWith('/tests') || value.startsWith('tests/')) return 'tests';
    if (value.includes('/reports/') || value.includes('/docs/') || value.startsWith('reports/') || value.startsWith('docs/')) return 'reports';
    if (value.includes('/data/') || value.startsWith('data/') || value.includes('fixture')) return 'data';
    return 'code';
  };

  const moveFocus = (buttons, currentIndex, event) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const direction = ['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1;
    let next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : currentIndex + direction;
    next = (next + buttons.length) % buttons.length;
    buttons[next].focus();
    buttons[next].click();
  };

  const updateURL = (mode = 'replace') => {
    if (mode === 'none') return;
    const url = new URL(location.href);
    url.searchParams.set('project', activeProject);
    url.searchParams.set('view', activeView);
    if (activeMetric) url.searchParams.set('metric', activeMetric); else url.searchParams.delete('metric');
    if (activeFilter !== 'all') url.searchParams.set('filter', activeFilter); else url.searchParams.delete('filter');
    const query = one('[data-search]')?.value.trim();
    if (query) url.searchParams.set('q', query); else url.searchParams.delete('q');
    history[mode === 'push' ? 'pushState' : 'replaceState']({ project: activeProject, view: activeView }, '', url);
  };

  const renderTable = (project, metric) => {
    const head = one('[data-table-head]');
    const body = one('[data-table-body]');
    let first = 'Observation';
    if (activeProject === 'casuallab') first = 'Model';
    if (activeProject === 'macroeconomics') first = 'Backtest mode';
    if (activeProject === 'realestate') first = 'Rate-gap bucket';
    if (activeProject === 'tariff-incidence') first = 'Window';
    if (activeProject === 'microstructure') first = 'Distribution point';
    head.innerHTML = `<tr><th>${first}</th><th>${escapeHTML(metric.label)}</th><th>Context</th></tr>`;
    body.innerHTML = project.series.map((row) => {
      const x = xDescriptor(activeProject, row);
      const value = activeProject === 'microstructure' && row.status === 'not_run' ? 'NOT RUN' : formatValue(row[metric.id], metric);
      return `<tr><td>${escapeHTML(activeProject === 'realestate' ? row.bucket : x.label)}</td><td>${escapeHTML(value)}</td><td>${escapeHTML(context(activeProject, row))}</td></tr>`;
    }).join('');
  };

  const renderChart = (project, metric) => {
    const chart = one('[data-chart]');
    const width = 840;
    const height = 360;
    const pad = { left: 64, right: 26, top: 22, bottom: 54 };
    const plotWidth = width - pad.left - pad.right;
    const plotHeight = height - pad.top - pad.bottom;
    const values = project.series.map((row) => Number(row[metric.id]));
    const rawMin = Math.min(...values);
    const rawMax = Math.max(...values);
    let referenceValues = [];
    let referenceLabel = '';
    if (activeProject === 'tariff-incidence' && project.reference) {
      if (metric.id === 'landed') {
        referenceValues = [project.reference.mechanical_log];
        referenceLabel = `Mechanical tariff: ${signed(project.reference.mechanical_log)}`;
      } else if (metric.id === 'customs') {
        referenceValues = [-project.reference.customs_bound, project.reference.customs_bound];
        referenceLabel = `Bound: ±${project.reference.customs_bound.toFixed(3)}`;
      }
    }
    let yMin = Math.min(0, rawMin, ...referenceValues);
    let yMax = Math.max(0, rawMax, ...referenceValues);
    if (yMin === yMax) yMax = yMin + 1;
    const span = yMax - yMin;
    yMax += span * 0.08;
    if (yMin < 0) yMin -= span * 0.05;
    const y = (value) => pad.top + (yMax - value) / (yMax - yMin) * plotHeight;
    const zeroY = y(0);
    const numericX = activeProject === 'realestate';
    const xValues = project.series.map((row, index) => numericX ? xDescriptor(activeProject, row).numeric : index);
    const xMin = Math.min(...xValues);
    const xMax = Math.max(...xValues);
    const x = (value, index) => numericX ? pad.left + (value - xMin) / Math.max(1e-9, xMax - xMin) * plotWidth : pad.left + (index + .5) / project.series.length * plotWidth;
    const points = project.series.map((row, index) => ({ row, index, x: x(xValues[index], index), y: y(values[index]), value: values[index], label: xDescriptor(activeProject, row).label }));
    const grid = Array.from({ length: 5 }, (_, index) => {
      const ratio = index / 4;
      const value = yMax - ratio * (yMax - yMin);
      const py = pad.top + ratio * plotHeight;
      return `<line class="chart-grid-line" x1="${pad.left}" y1="${py}" x2="${width - pad.right}" y2="${py}"></line><text class="chart-axis-text" x="${pad.left - 10}" y="${py + 3}" text-anchor="end">${escapeHTML(formatAxis(value, metric))}</text>`;
    }).join('');
    const tickIndices = points.map((point) => point.index);
    const ticks = tickIndices.map((index) => `<text class="chart-axis-text" x="${points[index].x}" y="${height - 24}" text-anchor="middle">${escapeHTML(points[index].label)}</text>`).join('');
    let series = '';
    let marks;
    if (metric.type === 'bar') {
      const barWidth = Math.min(92, plotWidth / points.length * .5);
      marks = points.map((point) => {
        const top = Math.min(point.y, zeroY);
        const barHeight = Math.max(2, Math.abs(zeroY - point.y));
        const label = `${point.label}, ${metric.label}: ${formatValue(point.value, metric)}, ${context(activeProject, point.row)}`;
        const tip = escapeHTML(`<strong>${point.label}</strong><br>${metric.label}: ${formatValue(point.value, metric)}<br>${context(activeProject, point.row)}`);
        if (activeProject === 'microstructure' && point.row.status === 'not_run') {
          return `<g class="chart-mark chart-status-mark" tabindex="0" role="img" aria-label="${escapeHTML(`${point.label}: not run; ${point.row.outcome}`)}" data-cx="${point.x}" data-cy="${zeroY - 13}" data-tip="${tip}"><rect class="chart-not-run" x="${point.x - 39}" y="${zeroY - 24}" width="78" height="22" rx="11"></rect><text class="chart-status-text" x="${point.x}" y="${zeroY - 9}" text-anchor="middle">NOT RUN</text></g>`;
        }
        if (activeProject === 'microstructure' && point.row.status === 'passed' && point.value === 0) {
          return `<g class="chart-mark chart-status-mark" tabindex="0" role="img" aria-label="${escapeHTML(label)}" data-cx="${point.x}" data-cy="${zeroY - 13}" data-tip="${tip}"><rect class="chart-pass" x="${point.x - 29}" y="${zeroY - 24}" width="58" height="22" rx="11"></rect><text class="chart-status-text" x="${point.x}" y="${zeroY - 9}" text-anchor="middle">0 · PASS</text></g>`;
        }
        return `<g class="chart-mark" tabindex="0" role="img" aria-label="${escapeHTML(label)}" data-cx="${point.x}" data-cy="${top}" data-tip="${tip}"><rect class="chart-bar" x="${point.x - barWidth / 2}" y="${top}" width="${barWidth}" height="${barHeight}" rx="6"></rect></g>`;
      }).join('');
    } else {
      const line = points.map((point) => `${point.x},${point.y}`).join(' ');
      const baseline = Math.max(pad.top, Math.min(height - pad.bottom, zeroY));
      const area = `M ${points[0].x} ${baseline} L ${points.map((point) => `${point.x} ${point.y}`).join(' L ')} L ${points[points.length - 1].x} ${baseline} Z`;
      series = `<path class="chart-area" d="${area}"></path><polyline class="chart-line" points="${line}"></polyline>`;
      marks = points.map((point) => {
        const label = `${point.label}, ${metric.label}: ${formatValue(point.value, metric)}, ${context(activeProject, point.row)}`;
        const tip = `<strong>${point.label}</strong><br>${metric.label}: ${formatValue(point.value, metric)}<br>${context(activeProject, point.row)}`;
        return `<g class="chart-mark" tabindex="0" role="img" aria-label="${escapeHTML(label)}" data-cx="${point.x}" data-cy="${point.y}" data-tip="${escapeHTML(tip)}"><circle cx="${point.x}" cy="${point.y}" r="5"></circle></g>`;
      }).join('');
    }
    const zeroLine = yMin < 0 || rawMin < 0 ? `<line class="chart-zero-line" x1="${pad.left}" y1="${zeroY}" x2="${width - pad.right}" y2="${zeroY}"></line>` : '';
    const referenceGraphic = referenceValues.map((value) => {
      const py = y(value);
      const label = referenceValues.length > 1 ? `${value > 0 ? '+' : '−'} bound` : referenceLabel;
      return `<line class="chart-reference-line" x1="${pad.left}" y1="${py}" x2="${width - pad.right}" y2="${py}"></line><text class="chart-reference-text" x="${width - pad.right}" y="${py - 6}" text-anchor="end">${escapeHTML(label)}</text>`;
    }).join('');
    const title = `${project.title}: ${metric.label}`;
    chart.setAttribute('aria-label', title);
    chart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="group" aria-label="${escapeHTML(title)}">${grid}${zeroLine}${referenceGraphic}${series}${marks}${ticks}</svg><div class="chart-tooltip" data-tooltip hidden></div>`;
    one('[data-chart-legend]').innerHTML = `<span>${escapeHTML(metric.label)} · ${escapeHTML(metric.unit)}${referenceLabel ? ` · ${escapeHTML(referenceLabel)}` : ''}</span><span>${project.series.length} observations · hover, tap, or focus a mark</span>`;
    const tooltip = one('[data-tooltip]');
    const show = (mark) => {
      const svg = chart.querySelector('svg');
      tooltip.innerHTML = mark.dataset.tip;
      tooltip.hidden = false;
      const desiredLeft = Number(mark.dataset.cx) / width * svg.clientWidth;
      const desiredTop = Number(mark.dataset.cy) / height * svg.clientHeight;
      const halfWidth = tooltip.offsetWidth / 2;
      tooltip.style.left = `${Math.max(halfWidth + 8, Math.min(svg.clientWidth - halfWidth - 8, desiredLeft))}px`;
      tooltip.style.top = `${desiredTop}px`;
      tooltip.classList.toggle('is-below', desiredTop < tooltip.offsetHeight * 1.25);
    };
    chart.querySelectorAll('.chart-mark').forEach((mark) => {
      mark.addEventListener('pointerenter', () => show(mark));
      mark.addEventListener('pointerleave', () => { tooltip.hidden = true; });
      mark.addEventListener('pointercancel', () => { tooltip.hidden = true; });
      mark.addEventListener('focus', () => show(mark));
      mark.addEventListener('blur', () => { tooltip.hidden = true; });
      mark.addEventListener('click', (event) => { event.stopPropagation(); show(mark); });
    });
    chart.onclick = (event) => { if (!event.target.closest('.chart-mark')) tooltip.hidden = true; };
    chart.onkeydown = (event) => { if (event.key === 'Escape') tooltip.hidden = true; };
    renderTable(project, metric);
  };

  const money = (value) => `${Number(value) < 0 ? '−' : Number(value) > 0 ? '+' : ''}$${Math.abs(Number(value)).toFixed(2)}`;
  const basisPoints = (value) => `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(2)} bp`;
  const endpointLabel = (value) => ({ event_20: '20 events', event_100: '100 events', clock_1000ms: '1 second', clock_5000ms: '5 seconds' }[value] || value);
  const phaseLabel = (value) => value === 'primary_test' ? 'Primary pseudo-heldout' : 'Replication pseudo-heldout';
  let backtestSelection = { symbol: 'BTCUSDT', phase: 'primary_test', endpoint: 'clock_1000ms', decision: 1, order: 1 };

  const renderBacktestExplorer = () => {
    const root = one('[data-backtest-explorer]');
    if (!root || activeProject !== 'microstructure') return;
    if (!backtestReference) {
      root.innerHTML = '<p class="backtest-unavailable">The bounded scenario summary could not load. The distribution chart remains available.</p>';
      return;
    }
    const { design, overview, scenarios, disclaimer, provenance } = backtestReference;
    const option = (value, selected, label = value) => `<option value="${escapeHTML(value)}"${value === selected ? ' selected' : ''}>${escapeHTML(label)}</option>`;
    const match = scenarios.find((row) => row.symbol === backtestSelection.symbol && row.phase === backtestSelection.phase
      && row.endpoint === backtestSelection.endpoint && row.decision_latency_events === backtestSelection.decision
      && row.order_latency_events === backtestSelection.order) || backtestReference.default_scenario;
    backtestSelection = { symbol: match.symbol, phase: match.phase, endpoint: match.endpoint, decision: match.decision_latency_events, order: match.order_latency_events };
    const latencyButtons = design.decision_latency_events.flatMap((decision) => design.order_latency_events.map((order) => {
      const selected = decision === backtestSelection.decision && order === backtestSelection.order;
      return `<button type="button" role="radio" aria-checked="${selected}" tabindex="${selected ? 0 : -1}" data-latency-cell data-decision="${decision}" data-order="${order}"><span>d${decision}</span><small>o${order}</small></button>`;
    })).join('');
    root.innerHTML = `<div class="backtest-overview" aria-label="Scenario distribution overview">
        <div><span>Gross-positive</span><strong>${overview.gross_positive_count} / ${overview.scenario_count}</strong></div>
        <div><span>Net-positive</span><strong>${overview.net_positive_count} / ${overview.scenario_count}</strong></div>
        <div><span>Median net edge</span><strong>${basisPoints(overview.net_edge_bps.median)}</strong></div>
        <div><span>Median max drawdown</span><strong>${basisPoints(overview.max_drawdown_bps_of_turnover.median)}</strong></div>
      </div>
      <div class="backtest-controls">
        <div class="backtest-selects">
          <label>Symbol<select data-backtest-filter="symbol">${design.symbols.map((value) => option(value, backtestSelection.symbol)).join('')}</select></label>
          <label>Phase<select data-backtest-filter="phase">${design.evaluation_phases.map((value) => option(value, backtestSelection.phase, phaseLabel(value))).join('')}</select></label>
          <label>Horizon<select data-backtest-filter="endpoint">${design.endpoints.map((value) => option(value, backtestSelection.endpoint, endpointLabel(value))).join('')}</select></label>
        </div>
        <div class="latency-control"><div><span>Latency grid</span><small>decision × order events</small></div><div class="latency-grid" role="radiogroup" aria-label="Decision and order latency event grid">${latencyButtons}</div></div>
      </div>
      <article class="selected-scenario" aria-live="polite">
        <header><div><span>Selected scenario</span><strong>${escapeHTML(match.symbol)} · ${escapeHTML(phaseLabel(match.phase))} · ${escapeHTML(endpointLabel(match.endpoint))}</strong></div><small>d${match.decision_latency_events} / o${match.order_latency_events}</small></header>
        <div class="scenario-flow" aria-label="Gross profit and loss minus fees approximately equals net profit and loss after display rounding"><div><span>Gross P&amp;L</span><strong>${money(match.gross_pnl_usdt)}</strong></div><i aria-hidden="true">−</i><div><span>Fees</span><strong>$${Math.abs(Number(match.fees_usdt)).toFixed(2)}</strong></div><i aria-hidden="true" title="Rounded display">≈</i><div class="is-net"><span>Net P&amp;L</span><strong>${money(match.net_pnl_usdt)}</strong></div></div>
        <div class="scenario-metrics"><div><span>Net edge</span><strong>${basisPoints(match.net_edge_bps)}</strong></div><div><span>Max drawdown</span><strong>${money(-Math.abs(match.max_drawdown_usdt))}</strong></div><div><span>Drawdown / turnover</span><strong>${basisPoints(match.max_drawdown_bps_of_turnover)}</strong></div><div><span>Orders / fills</span><strong>${Number(match.orders).toLocaleString('en-US')} / ${Number(match.fills).toLocaleString('en-US')}</strong></div></div>
      </article>
      <div class="backtest-provenance"><p><strong>Exploratory simulation · research reference only.</strong> ${escapeHTML(disclaimer)}</p><p>${provenance.verified_files} files verified, ${provenance.failed_files} failures. Scenarios overlap and are a distribution, not a portfolio total. <a href="./microstructure_backtest_reference.json">Open bounded JSON</a>.</p></div>`;
    root.querySelectorAll('[data-backtest-filter]').forEach((select) => select.addEventListener('change', () => {
      backtestSelection[select.dataset.backtestFilter] = select.value;
      renderBacktestExplorer();
    }));
    const cells = [...root.querySelectorAll('[data-latency-cell]')];
    cells.forEach((button) => {
      button.addEventListener('click', () => {
        backtestSelection.decision = Number(button.dataset.decision);
        backtestSelection.order = Number(button.dataset.order);
        renderBacktestExplorer();
        root.querySelector(`[data-decision="${backtestSelection.decision}"][data-order="${backtestSelection.order}"]`)?.focus();
      });
      button.addEventListener('keydown', (event) => {
        if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const current = cells.indexOf(button);
        const columns = design.order_latency_events.length;
        const delta = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : event.key === 'ArrowUp' ? -columns : columns;
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? cells.length - 1 : Math.max(0, Math.min(cells.length - 1, current + delta));
        cells[next].click();
      });
    });
  };

  const renderEvidence = () => {
    if (!evidence) return;
    const project = evidence.projects[activeProject];
    const meta = META[activeProject];
    if (!project.metrics.some((item) => item.id === activeMetric)) activeMetric = project.default_metric;
    const metric = project.metrics.find((item) => item.id === activeMetric) || project.metrics[0];
    one('#lab').dataset.accent = meta.accent;
    const metricCount = one('[data-active-metrics]');
    if (metricCount) metricCount.textContent = project.metrics.length.toLocaleString('en-US');
    const text = {
      '[data-portfolio-field]': meta.field,
      '[data-portfolio-title]': meta.portfolioTitle,
      '[data-portfolio-summary]': meta.portfolioSummary,
      '[data-portfolio-value]': meta.portfolioValue,
      '[data-portfolio-label]': meta.portfolioLabel,
      '[data-evidence]': project.evidence,
      '[data-period]': project.period,
      '[data-question]': project.question,
      '[data-note]': project.note,
      '[data-method]': project.method,
      '[data-finding]': project.finding,
      '[data-chart-caption]': project.chart_caption,
      '[data-headline]': project.headline.value,
      '[data-headline-label]': project.headline.label,
      '[data-source]': project.source,
      '[data-note-evidence]': project.evidence,
      '[data-note-boundary]': project.note,
      '[data-note-source]': project.source.split('/').pop(),
      '[data-trail-question]': project.question,
      '[data-trail-method]': project.method,
      '[data-trail-finding]': project.finding,
      '[data-trail-boundary]': project.note,
      '[data-trail-source]': project.source.split('/').pop()
    };
    Object.entries(text).forEach(([selector, value]) => { one(selector).textContent = value; });
    one('[data-project-page]').href = meta.page;
    one('[data-dataset]').href = project.source_url || datasetFileURL(project.source, evidence.dataset_revision);
    one('[data-source-code]').href = meta.source;
    const performance = one('[data-micro-performance]');
    if (performance) performance.hidden = activeProject !== 'microstructure';
    const projectPanel = one('#project-panel');
    if (projectPanel) projectPanel.setAttribute('aria-labelledby', `project-tab-${activeProject}`);
    all('[data-project]').forEach((button) => {
      const selected = button.dataset.project === activeProject;
      button.classList.toggle('is-active', selected);
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    const metricRoot = one('[data-metrics]');
    metricRoot.innerHTML = project.metrics.map((item) => `<button type="button" class="${item.id === metric.id ? 'is-active' : ''}" data-metric="${escapeHTML(item.id)}" aria-pressed="${item.id === metric.id}">${escapeHTML(item.label)}</button>`).join('');
    const metricButtons = all('[data-metric]');
    metricButtons.forEach((button, index) => {
      button.addEventListener('click', () => { activeMetric = button.dataset.metric; renderEvidence(); updateURL(); });
      button.addEventListener('keydown', (event) => moveFocus(metricButtons, index, event));
    });
    renderChart(project, metric);
    renderBacktestExplorer();
    renderPortfolio();
  };

  const renderPortfolio = () => {
    const dataFilter = one('[data-filter="data"]');
    if (dataFilter) dataFilter.textContent = activeProject === 'microstructure' ? 'Data paths' : 'Data';
  };

  const renderDirectories = () => {
    const root = one('[data-directory-bars]');
    if (!root) return;
    if (!rows.length) { root.innerHTML = '<div class="loading small">No paths available.</div>'; return; }
    const prefix = `${META[activeProject].folder}/`;
    const counts = {};
    rows.forEach((row) => {
      const relative = row.path.startsWith(prefix) ? row.path.slice(prefix.length) : row.path;
      const directory = relative.includes('/') ? relative.split('/')[0] : '(root)';
      counts[directory] = (counts[directory] || 0) + 1;
    });
    const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 7);
    const max = Math.max(...top.map((item) => item[1]));
    root.innerHTML = top.map(([name, count]) => `<div class="directory-row"><span title="${escapeHTML(name)}">${escapeHTML(name)}</span><div><i style="--size:${(count / max * 100).toFixed(2)}%"></i></div><strong>${count.toLocaleString('en-US')}</strong></div>`).join('');
  };

  const renderFiles = () => {
    const query = (one('[data-search]')?.value || '').trim().toLowerCase();
    const visible = rows.filter((row) => (!query || row.path.toLowerCase().includes(query)) && (activeFilter === 'all' || row.category === activeFilter));
    const shown = visible.slice(0, 180);
    one('[data-files]').innerHTML = shown.map((row) => `<tr><td><a class="file-link" href="${datasetFileURL(row.path, evidence.dataset_revision)}">${escapeHTML(row.path)}</a></td><td>${row.category}</td><td>${byteSize(row.size)}</td></tr>`).join('');
    one('[data-empty]').hidden = visible.length > 0;
    one('[data-result-count]').textContent = `${visible.length.toLocaleString('en-US')} match${visible.length === 1 ? '' : 'es'}${visible.length > shown.length ? ` · first ${shown.length} shown` : ''}`;
  };

  const loadCatalog = async () => {
    const slug = activeProject;
    const folder = META[slug].folder;
    one('[data-file-status]').textContent = 'Loading the pinned file index…';
    try {
      if (!cache[slug]) {
        const response = await fetch(`./catalog/${folder}.json`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        cache[slug] = await response.json();
      }
      if (slug !== activeProject) return;
      rows = cache[slug].map((item) => ({ path: item.path || '', size: item.size ?? null, category: item.category || category(item.path || '') }));
      const revision = (evidence?.dataset_revision || '5329ac0f88ba').slice(0, 12);
      one('[data-file-status]').textContent = `Connected to ${REPO} at ${revision}.`;
      renderFiles();
      renderDirectories();
    } catch (error) {
      if (slug !== activeProject) return;
      rows = [];
      one('[data-file-status]').textContent = `File index unavailable (${error.message}). Evidence links remain open.`;
      renderFiles();
      renderDirectories();
    }
  };

  const setView = (view, historyMode = 'replace') => {
    activeView = VIEWS.includes(view) ? view : 'signal';
    all('[data-view-panel]').forEach((panel) => { panel.hidden = panel.dataset.viewPanel !== activeView; });
    const buttons = all('[data-view]');
    buttons.forEach((button) => {
      const selected = button.dataset.view === activeView;
      button.classList.toggle('is-active', selected);
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    if (activeView === 'files') loadCatalog();
    updateURL(historyMode);
  };

  const selectProject = (slug, historyMode = 'push') => {
    if (!ORDER.includes(slug)) return;
    activeProject = slug;
    activeMetric = null;
    rows = cache[slug] || [];
    renderEvidence();
    if (activeView === 'files') loadCatalog();
    updateURL(historyMode);
    const selectedButton = one(`[data-project="${slug}"]`);
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    selectedButton?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'nearest', inline: 'center' });
  };

  const projectButtons = all('[data-project]');
  projectButtons.forEach((button, index) => {
    button.addEventListener('click', () => selectProject(button.dataset.project));
    button.addEventListener('keydown', (event) => moveFocus(projectButtons, index, event));
  });
  const viewButtons = all('[data-view]');
  viewButtons.forEach((button, index) => {
    button.addEventListener('click', () => setView(button.dataset.view, 'push'));
    button.addEventListener('keydown', (event) => moveFocus(viewButtons, index, event));
  });
  all('[data-filter]').forEach((button) => button.addEventListener('click', () => {
    activeFilter = button.dataset.filter;
    all('[data-filter]').forEach((candidate) => {
      const selected = candidate === button;
      candidate.classList.toggle('is-active', selected);
      candidate.setAttribute('aria-pressed', String(selected));
    });
    renderFiles();
    updateURL();
  }));
  const search = one('[data-search]');
  search.value = params.get('q') || '';
  search.addEventListener('input', () => { renderFiles(); updateURL(); });
  all('[data-filter]').forEach((button) => {
    const selected = button.dataset.filter === activeFilter;
    button.classList.toggle('is-active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });

  one('[data-share]').addEventListener('click', async () => {
    updateURL();
    const status = one('[data-share-status]');
    const shareButton = one('[data-share]');
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(location.href);
      else {
        const field = document.createElement('textarea');
        field.value = location.href;
        document.body.appendChild(field);
        field.select();
        document.execCommand('copy');
        field.remove();
      }
      status.textContent = 'View link copied';
      shareButton.textContent = 'Copied';
    } catch (error) {
      status.textContent = 'Copy unavailable';
      shareButton.textContent = 'Copy failed';
    }
    window.setTimeout(() => { status.textContent = ''; shareButton.textContent = 'Share view'; }, 2400);
  });

  one('[data-reset]').addEventListener('click', () => {
    activeProject = 'casuallab';
    activeMetric = null;
    activeFilter = 'all';
    search.value = '';
    all('[data-filter]').forEach((button) => {
      const selected = button.dataset.filter === 'all';
      button.classList.toggle('is-active', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
    selectProject(activeProject, 'none');
    setView('signal', 'push');
  });

  window.addEventListener('popstate', () => {
    const next = new URLSearchParams(location.search);
    activeProject = ORDER.includes(next.get('project')) ? next.get('project') : 'casuallab';
    activeMetric = next.get('metric');
    activeView = VIEWS.includes(next.get('view')) ? next.get('view') : 'signal';
    activeFilter = ['all', 'code', 'data', 'reports', 'tests'].includes(next.get('filter')) ? next.get('filter') : 'all';
    search.value = next.get('q') || '';
    all('[data-filter]').forEach((button) => {
      const selected = button.dataset.filter === activeFilter;
      button.classList.toggle('is-active', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
    if (!evidence) return;
    rows = cache[activeProject] || [];
    renderEvidence();
    setView(activeView, 'none');
  });

  Promise.all([
    fetch('./evidence.json').then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    }),
    fetch('./microstructure_backtest_reference.json').then((response) => response.ok ? response.json() : null).catch(() => null)
  ])
    .then(([payload, reference]) => {
      evidence = payload;
      backtestReference = reference;
      all('[data-revision]').forEach((node) => { node.textContent = `Dataset revision ${payload.dataset_revision.slice(0, 12)}`; });
      renderEvidence();
      setView(activeView, 'replace');
    })
    .catch(() => {
      one('[data-chart]').innerHTML = '<div class="loading">Evidence failed to load. The linked Dataset remains available.</div>';
      one('[data-file-status]').textContent = 'Evidence index unavailable.';
    });
})();
