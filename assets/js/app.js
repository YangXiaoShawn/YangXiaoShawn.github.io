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

  const studio = document.querySelector('[data-research-studio]');
  const projectButtons = [...document.querySelectorAll('[data-studio-project]')];
  const stageButtons = [...document.querySelectorAll('[data-studio-stage]')];
  const stageOrder = ['question', 'design', 'evidence', 'boundary'];
  const projectOrder = ['casuallab', 'macroeconomics', 'realestate', 'tariff-incidence'];

  const fallbackProjects = [
    {
      title: 'CasualLab', slug: 'casuallab', field: 'causal', accent: 'teal',
      summary: 'Experimental causal inference and policy simulation with public examples and estimator validation workflows.',
      research_question: 'How do causal mechanisms and heterogeneous treatment effects shape market outcomes and policy interventions?',
      tags: ['Causal inference', 'Policy simulation', 'Heterogeneity'],
      site_url: 'https://yangxiaoshawn.github.io/projects/casuallab/',
      github_url: 'https://github.com/YangXiaoShawn/open-economic-quant-casuallab',
      dataset_url: 'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/CasualLab'
    },
    {
      title: 'Macroeconomics', slug: 'macroeconomics', field: 'macro', accent: 'blue',
      summary: 'Real-time macroeconomic forecasting, vintage reconstruction, and policy-shock analysis with guarded public-source adapters.',
      research_question: 'How do release revisions and the information available at each vintage affect nowcast and forecast quality?',
      tags: ['Nowcasting', 'Vintage data', 'Policy forecasting'],
      site_url: 'https://yangxiaoshawn.github.io/projects/macroeconomics/',
      github_url: 'https://github.com/YangXiaoShawn/open-economic-quant-macroeconomics',
      dataset_url: 'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/Macroeconomics'
    },
    {
      title: 'Mortgage Rate Lock-In and Housing Market Dynamics', slug: 'realestate', field: 'housing', accent: 'amber',
      summary: 'Housing-finance research on how mortgage rate lock-in relates to exits, local activity, prices, and residential construction.',
      research_question: "How does the gap between homeowners' existing mortgage rates and current market rates affect mortgage exits and housing activity?",
      tags: ['Housing economics', 'Mortgage lock-in', 'Event studies'],
      site_url: 'https://yangxiaoshawn.github.io/projects/realestate/',
      github_url: 'https://github.com/YangXiaoShawn/YangXiaoShawn.github.io/tree/main/realestate',
      dataset_url: 'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/RealEstate'
    },
    {
      title: 'Tariff Incidence, Supply-Chain Reallocation, and Domestic Propagation', slug: 'tariff-incidence', field: 'trade', accent: 'green',
      summary: 'Official-data research on tariff pass-through, sourcing changes, and downstream input-output exposure.',
      research_question: 'How did U.S. product-level tariffs on imports from China pass through to importers, reshape sourcing, and propagate domestically?',
      tags: ['International trade', 'Tariff incidence', 'Supply chains'],
      site_url: 'https://yangxiaoshawn.github.io/projects/tariff-incidence/',
      github_url: 'https://github.com/YangXiaoShawn/open-economic-quant-tariff-incidence',
      dataset_url: 'https://huggingface.co/datasets/ShawnChamberlain/open-economic-quant-research-data/tree/main/TariffIncidence'
    }
  ];

  const studioDetails = {
    casuallab: {
      field: 'Causal inference / Market design',
      design: 'Define the estimand first, state identification assumptions, and recover effects on fixtures or authorized public data.',
      evidence: 'Estimator checks, heterogeneous-effect diagnostics, reproducible fixtures, and traceable result manifests connect method to output.',
      boundary: 'Public examples demonstrate the workflow and estimator behavior; they do not claim effects for populations the data do not represent.'
    },
    macroeconomics: {
      field: 'Real-time macro / Forecasting',
      design: 'Align every observation to what was knowable at the forecast date, then compare models on the same vintage-consistent information set.',
      evidence: 'Release clocks, guarded agency adapters, rolling backtests, and revision audits expose where apparent accuracy comes from.',
      boundary: 'A revised public series is not treated as real-time evidence when an archival vintage is unavailable; that limitation remains visible.'
    },
    realestate: {
      field: 'Housing economics / Mortgage finance',
      design: 'Construct point-in-time lock-in measures, model mortgage exits, and freeze local exposure before event-study outcomes are observed.',
      evidence: 'Hazard estimates, aggregate market responses, pre-trend checks, and tiered evidence labels separate supported findings from illustration.',
      boundary: 'Registered microdata and public aggregates have different inferential reach; simulations are labeled as simulations, never forecasts.'
    },
    'tariff-incidence': {
      field: 'International trade / Applied econometrics',
      design: 'Parse legal notices into a provenance-stamped HS10 panel, then estimate each tariff wave in a stacked research design.',
      evidence: 'Pass-through, quantities, sourcing, and downstream exposure are tested outcome by outcome with pre-trends, placebos, and sensitivity checks.',
      boundary: 'Causal language is licensed only where diagnostics pass; structural counterfactuals remain distinct from directly observed evidence.'
    }
  };

  let projects = fallbackProjects;
  let activeProject = projectOrder.includes(location.hash.slice(1)) ? location.hash.slice(1) : projectOrder[0];
  let activeStage = 'question';

  const setText = (selector, value) => {
    const node = document.querySelector(selector);
    if (node) node.textContent = value;
  };

  const renderStage = () => {
    if (!studio) return;
    const project = projects.find((item) => item.slug === activeProject) || projects[0];
    const detail = studioDetails[project.slug];
    const stageIndex = stageOrder.indexOf(activeStage);
    const titles = ['What the project asks', 'How the design works', 'What you can inspect', 'Where the claim stops'];
    const copy = activeStage === 'question' ? project.research_question : detail[activeStage];
    setText('[data-stage-index]', String(stageIndex + 1).padStart(2, '0'));
    setText('[data-stage-title]', titles[stageIndex]);
    setText('[data-stage-copy]', copy);
    stageButtons.forEach((button) => {
      const selected = button.dataset.studioStage === activeStage;
      button.classList.toggle('is-active', selected);
      button.setAttribute('aria-selected', String(selected));
    });
    document.querySelectorAll('.evidence-path span').forEach((step, index) => {
      step.classList.toggle('is-current', index <= stageIndex);
    });
  };

  const renderStudio = () => {
    if (!studio) return;
    const project = projects.find((item) => item.slug === activeProject) || projects[0];
    const index = projectOrder.indexOf(project.slug);
    activeProject = project.slug;
    studio.dataset.accent = project.accent || 'teal';
    setText('[data-studio-field]', studioDetails[project.slug].field);
    setText('[data-studio-counter]', `${String(index + 1).padStart(2, '0')} / ${String(projectOrder.length).padStart(2, '0')}`);
    setText('[data-studio-question]', project.research_question);
    setText('[data-studio-summary]', project.summary);
    const tags = document.querySelector('[data-studio-tags]');
    if (tags) tags.innerHTML = (project.tags || []).map((tag) => `<span>${escapeHTML(tag)}</span>`).join('');
    const page = document.querySelector('[data-studio-page]');
    const data = document.querySelector('[data-studio-data]');
    const source = document.querySelector('[data-studio-source]');
    if (page) page.href = `projects/${encodeURIComponent(project.slug)}/`;
    if (data) data.href = project.dataset_url;
    if (source) source.href = project.github_url;
    projectButtons.forEach((button) => {
      const selected = button.dataset.studioProject === project.slug;
      button.classList.toggle('is-active', selected);
      button.setAttribute('aria-selected', String(selected));
    });
    renderStage();
  };

  const moveTabFocus = (buttons, currentIndex, event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    let nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : currentIndex + (event.key === 'ArrowRight' ? 1 : -1);
    nextIndex = (nextIndex + buttons.length) % buttons.length;
    buttons[nextIndex].focus();
    buttons[nextIndex].click();
  };

  projectButtons.forEach((button, index) => {
    button.addEventListener('click', () => {
      activeProject = button.dataset.studioProject;
      activeStage = 'question';
      history.replaceState(null, '', `#${activeProject}`);
      renderStudio();
    });
    button.addEventListener('keydown', (event) => moveTabFocus(projectButtons, index, event));
  });

  stageButtons.forEach((button, index) => {
    button.addEventListener('click', () => {
      activeStage = button.dataset.studioStage;
      renderStage();
    });
    button.addEventListener('keydown', (event) => moveTabFocus(stageButtons, index, event));
  });

  if (studio) {
    renderStudio();
    fetch('assets/data/projects.json')
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then((payload) => {
        projects = payload.projects || fallbackProjects;
        renderStudio();
      })
      .catch(() => renderStudio());
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
