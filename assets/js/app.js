(() => {
  'use strict';

  const navToggle = document.querySelector('.nav-toggle');
  const siteNav = document.querySelector('.site-nav');
  if (navToggle && siteNav) {
    navToggle.addEventListener('click', () => {
      const expanded = navToggle.getAttribute('aria-expanded') === 'true';
      navToggle.setAttribute('aria-expanded', String(!expanded));
      siteNav.classList.toggle('is-open', !expanded);
    });
    siteNav.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => {
      navToggle.setAttribute('aria-expanded', 'false');
      siteNav.classList.remove('is-open');
    }));
  }

  document.querySelectorAll('[data-current-year]').forEach((node) => {
    node.textContent = new Date().getFullYear();
  });

  const escapeHTML = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[character]));

  const PROJECT_ORDER = ['casuallab', 'macroeconomics', 'realestate', 'tariff-incidence', 'microstructure'];
  const PROJECT_META = {
    casuallab: {
      short: 'NYC mobility', accent: 'teal', folder: 'CasualLab',
      page: 'projects/casuallab/',
      data: 'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/CasualLab'
    },
    macroeconomics: {
      short: 'Real-time macro', accent: 'blue', folder: 'Macroeconomics',
      page: 'projects/macroeconomics/',
      data: 'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/Macroeconomics'
    },
    realestate: {
      short: 'Housing lock-in', accent: 'amber', folder: 'RealEstate',
      page: 'projects/realestate/',
      data: 'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/RealEstate'
    },
    'tariff-incidence': {
      short: 'Tariff incidence', accent: 'green', folder: 'TariffIncidence',
      page: 'projects/tariff-incidence/',
      data: 'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/TariffIncidence'
    },
    microstructure: {
      short: 'Microstructure', accent: 'violet', folder: 'Microstructure',
      page: 'projects/microstructure/',
      data: 'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/Microstructure'
    }
  };

  const moveTabFocus = (buttons, currentIndex, event) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const direction = ['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1;
    let nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : currentIndex + direction;
    nextIndex = (nextIndex + buttons.length) % buttons.length;
    buttons[nextIndex].focus();
    buttons[nextIndex].click();
  };

  const compact = (value, digits = 1) => new Intl.NumberFormat('en', {
    notation: 'compact', maximumFractionDigits: digits
  }).format(value);

  const signed = (value, digits = 3) => `${value > 0 ? '+' : ''}${Number(value).toFixed(digits)}`;

  const formatValue = (value, metric) => {
    if (!Number.isFinite(Number(value))) return '—';
    const numeric = Number(value);
    if (metric.unit === 'trips') return compact(numeric, 2);
    if (metric.unit === 'USD') return `$${numeric.toFixed(2)}`;
    if (metric.unit === '%') return `${numeric.toFixed(metric.id === 'hazard' ? 3 : 2)}%`;
    if (['cells', 'rows', 'warnings'].includes(metric.unit)) return Math.round(numeric).toLocaleString('en-US');
    if (metric.unit === 'log points') return signed(numeric);
    return numeric.toLocaleString('en-US');
  };

  const formatAxis = (value, metric) => {
    const numeric = Number(value);
    if (['trips', 'cells', 'rows', 'warnings'].includes(metric.unit)) return compact(numeric, 1);
    if (metric.unit === 'USD') return `$${numeric.toFixed(0)}`;
    if (metric.unit === '%') return `${numeric.toFixed(numeric >= 10 ? 0 : 1)}%`;
    if (metric.unit === 'log points') return signed(numeric, 2);
    return numeric.toFixed(1);
  };

  const datasetFileURL = (source, revision) => {
    const path = String(source).split('/').map(encodeURIComponent).join('/');
    return `https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/blob/${encodeURIComponent(revision)}/${path}`;
  };

  const heroBars = document.querySelector('[data-hero-bars]');
  const heroModeButtons = [...document.querySelectorAll('[data-chart-mode]')];
  const signalLab = document.querySelector('[data-signal-lab]');
  const signalTabs = [...document.querySelectorAll('[data-signal-project]')];
  let evidencePayload = null;
  let activeProject = PROJECT_ORDER.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'casuallab';
  let activeMetric = null;
  let heroMode = 'files';
  const categoryLabel = (slug, category) => slug === 'microstructure' && category === 'data' ? 'data paths' : category;

  const renderHero = () => {
    if (!heroBars || !evidencePayload) return;
    const portfolio = evidencePayload.portfolio;
    const maxFiles = Math.max(...PROJECT_ORDER.map((slug) => portfolio.projects[slug].files));
    const mixColors = { code: '#6ee7d8', data: '#8eb8ff', reports: '#ffca6a', tests: '#7fe4aa' };
    const order = ['macroeconomics', 'casuallab', 'microstructure', 'tariff-incidence', 'realestate'];
    heroBars.innerHTML = order.map((slug) => {
      const project = portfolio.projects[slug];
      const selected = slug === activeProject;
      let track;
      let value;
      let label;
      if (heroMode === 'types') {
        const categories = ['code', 'data', 'reports', 'tests'];
        track = `<span class="bar-track is-mix">${categories.map((category) => {
          const share = project[category] / project.files * 100;
          return `<i title="${escapeHTML(categoryLabel(slug, category))}: ${project[category].toLocaleString('en-US')}" style="--mix-size:${share.toFixed(3)}%;--mix-color:${mixColors[category]}"></i>`;
        }).join('')}</span>`;
        const largest = categories.reduce((best, item) => project[item] > project[best] ? item : best, categories[0]);
        value = `${Math.round(project[largest] / project.files * 100)}%`;
        label = `${PROJECT_META[slug].short}: ${project.files.toLocaleString('en-US')} files; ${categories.map((category) => `${categoryLabel(slug, category)} ${project[category]}`).join(', ')}`;
      } else {
        track = `<span class="bar-track"><i style="--bar-size:${(project.files / maxFiles * 100).toFixed(2)}%"></i></span>`;
        value = project.files.toLocaleString('en-US');
        label = `${PROJECT_META[slug].short}: ${value} public files`;
      }
      return `<button class="hero-bar-row${selected ? ' is-active' : ''}" type="button" data-hero-project="${slug}" aria-pressed="${selected}" aria-label="${escapeHTML(label)}"><span class="bar-name">${escapeHTML(PROJECT_META[slug].short)}</span>${track}<strong>${value}</strong></button>`;
    }).join('');
    const caption = document.querySelector('[data-hero-caption]');
    if (caption) caption.textContent = heroMode === 'files' ? 'Files at the published revision' : `Mix: code · ${activeProject === 'microstructure' ? 'data paths' : 'data'} · reports · tests`;
    heroBars.querySelectorAll('[data-hero-project]').forEach((button) => button.addEventListener('click', () => {
      selectProject(button.dataset.heroProject);
    }));
  };

  heroModeButtons.forEach((button) => button.addEventListener('click', () => {
    heroMode = button.dataset.chartMode;
    heroModeButtons.forEach((candidate) => {
      const selected = candidate === button;
      candidate.classList.toggle('is-active', selected);
      candidate.setAttribute('aria-pressed', String(selected));
    });
    renderHero();
  }));

  const xDescriptor = (slug, row) => {
    if (slug === 'casuallab') return { numeric: row.hour, label: `${String(row.hour).padStart(2, '0')}:00` };
    if (slug === 'macroeconomics') return { numeric: null, label: row.mode };
    if (slug === 'realestate') return { numeric: row.mean_gap, label: `${row.mean_gap > 0 ? '+' : ''}${row.mean_gap.toFixed(2)} pp` };
    if (slug === 'microstructure') return { numeric: null, label: row.stage };
    return { numeric: null, label: row.window };
  };

  const supplementalTooltip = (slug, row) => {
    if (slug === 'macroeconomics') return `${row.feature_cells.toLocaleString('en-US')} feature cells`;
    if (slug === 'realestate') return `${row.bucket} · ${row.events.toLocaleString('en-US')} events`;
    if (slug === 'tariff-incidence') return `N = ${row.n.toLocaleString('en-US')}`;
    if (slug === 'microstructure') return row.outcome;
    return 'NYC TLC completed trips';
  };

  const renderSignalTable = (project, metric) => {
    const head = document.querySelector('[data-signal-table-head]');
    const body = document.querySelector('[data-signal-table-body]');
    if (!head || !body) return;
    let firstLabel = 'Observation';
    if (activeProject === 'casuallab') firstLabel = 'Hour';
    if (activeProject === 'macroeconomics') firstLabel = 'Backtest mode';
    if (activeProject === 'realestate') firstLabel = 'Rate-gap bucket';
    if (activeProject === 'tariff-incidence') firstLabel = 'Window';
    if (activeProject === 'microstructure') firstLabel = 'Pipeline gate';
    head.innerHTML = `<tr><th>${firstLabel}</th><th>${escapeHTML(metric.label)}</th><th>Context</th></tr>`;
    body.innerHTML = project.series.map((row) => {
      const x = xDescriptor(activeProject, row);
      return `<tr><td>${escapeHTML(activeProject === 'realestate' ? row.bucket : x.label)}</td><td>${escapeHTML(formatValue(row[metric.id], metric))}</td><td>${escapeHTML(supplementalTooltip(activeProject, row))}</td></tr>`;
    }).join('');
  };

  const renderChart = (project, metric) => {
    const chart = document.querySelector('[data-signal-chart]');
    const legend = document.querySelector('[data-chart-legend]');
    if (!chart) return;
    const width = 820;
    const height = 390;
    const pad = { left: 64, right: 26, top: 24, bottom: 56 };
    const plotWidth = width - pad.left - pad.right;
    const plotHeight = height - pad.top - pad.bottom;
    const values = project.series.map((row) => Number(row[metric.id]));
    const rawMin = Math.min(...values);
    const rawMax = Math.max(...values);
    let yMin = Math.min(0, rawMin);
    let yMax = Math.max(0, rawMax);
    if (yMin === yMax) yMax = yMin + 1;
    const span = yMax - yMin;
    yMax += span * 0.08;
    if (yMin < 0) yMin -= span * 0.05;
    const y = (value) => pad.top + (yMax - value) / (yMax - yMin) * plotHeight;
    const zeroY = y(0);
    const isNumericX = ['casuallab', 'realestate'].includes(activeProject);
    const xValues = project.series.map((row, index) => isNumericX ? xDescriptor(activeProject, row).numeric : index);
    const xMin = Math.min(...xValues);
    const xMax = Math.max(...xValues);
    const x = (value, index) => {
      if (isNumericX) return pad.left + (value - xMin) / Math.max(1e-9, xMax - xMin) * plotWidth;
      return pad.left + (index + 0.5) / project.series.length * plotWidth;
    };
    const points = project.series.map((row, index) => ({
      row,
      index,
      x: x(xValues[index], index),
      y: y(values[index]),
      value: values[index],
      label: xDescriptor(activeProject, row).label
    }));
    const grid = Array.from({ length: 5 }, (_, index) => {
      const ratio = index / 4;
      const value = yMax - ratio * (yMax - yMin);
      const py = pad.top + ratio * plotHeight;
      return `<line class="chart-grid-line" x1="${pad.left}" y1="${py}" x2="${width - pad.right}" y2="${py}"></line><text class="chart-axis-text" x="${pad.left - 10}" y="${py + 3}" text-anchor="end">${escapeHTML(formatAxis(value, metric))}</text>`;
    }).join('');
    let xTickIndices;
    if (activeProject === 'casuallab') xTickIndices = [0, 6, 12, 18, 23];
    else xTickIndices = points.map((point) => point.index);
    const ticks = xTickIndices.map((index) => {
      const point = points[index];
      return `<text class="chart-axis-text" x="${point.x}" y="${height - 25}" text-anchor="middle">${escapeHTML(point.label)}</text>`;
    }).join('');
    let marks;
    let seriesGraphic = '';
    if (metric.type === 'bar') {
      const barWidth = Math.min(92, plotWidth / points.length * 0.5);
      marks = points.map((point) => {
        const top = Math.min(point.y, zeroY);
        const barHeight = Math.max(2, Math.abs(zeroY - point.y));
        const aria = `${point.label}, ${metric.label}: ${formatValue(point.value, metric)}, ${supplementalTooltip(activeProject, point.row)}`;
        return `<g class="chart-mark" tabindex="0" role="img" aria-label="${escapeHTML(aria)}" data-cx="${point.x}" data-cy="${top}" data-tip="${escapeHTML(`<strong>${point.label}</strong><br>${metric.label}: ${formatValue(point.value, metric)}<br>${supplementalTooltip(activeProject, point.row)}`)}"><rect class="chart-bar" x="${point.x - barWidth / 2}" y="${top}" width="${barWidth}" height="${barHeight}" rx="6"></rect></g>`;
      }).join('');
    } else {
      const linePoints = points.map((point) => `${point.x},${point.y}`).join(' ');
      const baseline = Math.max(pad.top, Math.min(height - pad.bottom, zeroY));
      const areaPath = `M ${points[0].x} ${baseline} L ${points.map((point) => `${point.x} ${point.y}`).join(' L ')} L ${points[points.length - 1].x} ${baseline} Z`;
      seriesGraphic = `<path class="chart-area" d="${areaPath}"></path><polyline class="chart-line" points="${linePoints}"></polyline>`;
      marks = points.map((point) => {
        const aria = `${point.label}, ${metric.label}: ${formatValue(point.value, metric)}, ${supplementalTooltip(activeProject, point.row)}`;
        return `<g class="chart-mark" tabindex="0" role="img" aria-label="${escapeHTML(aria)}" data-cx="${point.x}" data-cy="${point.y}" data-tip="${escapeHTML(`<strong>${point.label}</strong><br>${metric.label}: ${formatValue(point.value, metric)}<br>${supplementalTooltip(activeProject, point.row)}`)}"><circle cx="${point.x}" cy="${point.y}" r="5"></circle></g>`;
      }).join('');
    }
    const zeroLine = yMin < 0 || rawMin < 0 ? `<line class="chart-zero-line" x1="${pad.left}" y1="${zeroY}" x2="${width - pad.right}" y2="${zeroY}"></line>` : '';
    const title = `${project.title}: ${metric.label} by ${activeProject === 'casuallab' ? 'hour' : activeProject === 'macroeconomics' ? 'backtest mode' : activeProject === 'realestate' ? 'rate gap' : activeProject === 'microstructure' ? 'pipeline gate' : 'analysis window'}`;
    chart.setAttribute('aria-label', title);
    chart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="group" aria-label="${escapeHTML(title)}">${grid}${zeroLine}${seriesGraphic}${marks}${ticks}</svg><div class="chart-tooltip" data-chart-tooltip hidden></div>`;
    if (legend) legend.innerHTML = `<span>${escapeHTML(metric.label)} · ${escapeHTML(metric.unit)}</span><span>${project.series.length.toLocaleString('en-US')} observations · hover, tap, or focus a mark</span>`;
    const tooltip = chart.querySelector('[data-chart-tooltip]');
    const show = (mark) => {
      if (!tooltip) return;
      const svg = chart.querySelector('svg');
      const chartWidth = svg ? svg.clientWidth : chart.clientWidth;
      const chartHeight = svg ? svg.clientHeight : chart.clientHeight;
      tooltip.innerHTML = mark.dataset.tip;
      tooltip.hidden = false;
      const desiredLeft = Number(mark.dataset.cx) / width * chartWidth;
      const desiredTop = Number(mark.dataset.cy) / height * chartHeight;
      const halfWidth = tooltip.offsetWidth / 2;
      tooltip.style.left = `${Math.max(halfWidth + 8, Math.min(chartWidth - halfWidth - 8, desiredLeft))}px`;
      tooltip.style.top = `${desiredTop}px`;
      tooltip.classList.toggle('is-below', desiredTop < tooltip.offsetHeight * 1.25);
    };
    chart.querySelectorAll('.chart-mark').forEach((mark) => {
      mark.addEventListener('pointerenter', () => show(mark));
      mark.addEventListener('pointerleave', () => { if (tooltip) tooltip.hidden = true; });
      mark.addEventListener('focus', () => show(mark));
      mark.addEventListener('blur', () => { if (tooltip) tooltip.hidden = true; });
      mark.addEventListener('click', (event) => { event.stopPropagation(); show(mark); });
    });
    chart.onclick = (event) => { if (!event.target.closest('.chart-mark') && tooltip) tooltip.hidden = true; };
    renderSignalTable(project, metric);
  };

  const renderSignal = () => {
    if (!signalLab || !evidencePayload) return;
    const project = evidencePayload.projects[activeProject];
    if (!project) return;
    const meta = PROJECT_META[activeProject];
    if (!project.metrics.some((metric) => metric.id === activeMetric)) activeMetric = project.default_metric;
    const metric = project.metrics.find((item) => item.id === activeMetric) || project.metrics[0];
    signalLab.dataset.accent = meta.accent;
    const fields = {
      '[data-signal-evidence]': project.evidence,
      '[data-signal-period]': project.period,
      '[data-signal-question]': project.question,
      '[data-signal-note]': project.note,
      '[data-signal-headline]': project.headline.value,
      '[data-signal-headline-label]': project.headline.label,
      '[data-signal-source]': project.source
    };
    Object.entries(fields).forEach(([selector, value]) => {
      const node = document.querySelector(selector);
      if (node) node.textContent = value;
    });
    const page = document.querySelector('[data-signal-page]');
    const data = document.querySelector('[data-signal-data]');
    const space = document.querySelector('[data-signal-space]');
    if (page) page.href = meta.page;
    if (data) data.href = datasetFileURL(project.source, evidencePayload.dataset_revision);
    if (space) space.href = `https://huggingface.co/spaces/ShawnChamberlain/open-economic-quant-research-observatory?project=${encodeURIComponent(activeProject)}`;
    const panel = document.getElementById('signal-panel');
    if (panel) panel.setAttribute('aria-labelledby', `signal-tab-${activeProject}`);
    signalTabs.forEach((tab) => {
      const selected = tab.dataset.signalProject === activeProject;
      tab.classList.toggle('is-active', selected);
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    const metricRoot = document.querySelector('[data-signal-metrics]');
    if (metricRoot) {
      metricRoot.innerHTML = project.metrics.map((item) => `<button type="button" class="${item.id === metric.id ? 'is-active' : ''}" data-signal-metric="${escapeHTML(item.id)}" aria-pressed="${item.id === metric.id}">${escapeHTML(item.label)}</button>`).join('');
      const metricButtons = [...metricRoot.querySelectorAll('[data-signal-metric]')];
      metricButtons.forEach((button, index) => {
        button.addEventListener('click', () => {
          activeMetric = button.dataset.signalMetric;
          renderSignal();
        });
        button.addEventListener('keydown', (event) => moveTabFocus(metricButtons, index, event));
      });
    }
    renderChart(project, metric);
    renderHero();
  };

  const selectProject = (slug) => {
    if (!PROJECT_ORDER.includes(slug)) return;
    activeProject = slug;
    activeMetric = null;
    history.replaceState(null, '', `#${slug}`);
    renderSignal();
  };

  signalTabs.forEach((button, index) => {
    button.addEventListener('click', () => selectProject(button.dataset.signalProject));
    button.addEventListener('keydown', (event) => moveTabFocus(signalTabs, index, event));
  });

  if (heroBars || signalLab) {
    fetch('assets/data/evidence.json')
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((payload) => {
        evidencePayload = payload;
        renderSignal();
        renderHero();
      })
      .catch(() => {
        const chart = document.querySelector('[data-signal-chart]');
        if (chart) chart.innerHTML = '<div class="chart-loading">The chart could not load. Open the live lab to inspect the published evidence.</div>';
      });
  }

  document.querySelectorAll('[data-sortable-table]').forEach((table) => table.querySelectorAll('th[data-sort-key]').forEach((header, index) => {
    header.tabIndex = 0;
    header.setAttribute('role', 'button');
    const sort = () => {
      const tbody = table.querySelector('tbody');
      if (!tbody) return;
      const direction = header.dataset.direction === 'asc' ? 'desc' : 'asc';
      table.querySelectorAll('th[data-sort-key]').forEach((item) => delete item.dataset.direction);
      header.dataset.direction = direction;
      [...tbody.rows]
        .sort((a, b) => (direction === 'asc' ? 1 : -1) * (a.cells[index]?.textContent.trim() || '').localeCompare(b.cells[index]?.textContent.trim() || '', undefined, { numeric: true }))
        .forEach((row) => tbody.appendChild(row));
    };
    header.addEventListener('click', sort);
    header.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        sort();
      }
    });
  }));
})();
