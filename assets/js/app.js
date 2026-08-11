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
  document.querySelectorAll('[data-current-year]').forEach((node) => { node.textContent = new Date().getFullYear(); });
  const escapeHTML = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
  const grid = document.querySelector('[data-project-grid]');
  const searchInput = document.querySelector('[data-project-search]');
  const filterButtons = [...document.querySelectorAll('[data-filter]')];
  const resultCount = document.querySelector('[data-result-count]');
  const noResults = document.querySelector('[data-no-results]');
  let projectCards = [];
  let activeFilter = 'all';
  const updateProjects = () => {
    if (!projectCards.length) return;
    const query = (searchInput?.value || '').trim().toLowerCase();
    let visibleCount = 0;
    projectCards.forEach((card) => {
      const haystack = [card.dataset.title, card.dataset.field, card.dataset.type, card.dataset.tags, card.textContent].join(' ').toLowerCase();
      const matchesSearch = !query || haystack.includes(query);
      const matchesFilter = activeFilter === 'all' || card.dataset.field === activeFilter || card.dataset.type === activeFilter || (card.dataset.tags || '').split(',').includes(activeFilter);
      card.hidden = !(matchesSearch && matchesFilter);
      if (!card.hidden) visibleCount += 1;
    });
    if (resultCount) resultCount.textContent = `${visibleCount} project${visibleCount === 1 ? '' : 's'} shown`;
    if (noResults) noResults.classList.toggle('is-visible', visibleCount === 0);
  };
  const renderCatalog = ({ projects = [] }) => {
    if (!grid) return;
    grid.innerHTML = projects.map((project, index) => {
      const tags = (project.tags || []).map((tag) => `<span class="tag">${escapeHTML(tag)}</span>`).join('');
      const tagData = [...(project.tags || []), project.status].join(',').toLowerCase().replaceAll(' ', '-');
      return `<article class="project-card" data-accent="${escapeHTML(project.accent)}" data-project-card data-title="${escapeHTML(project.title)}" data-field="${escapeHTML(project.field)}" data-type="${escapeHTML(project.status)}" data-tags="${escapeHTML(tagData)}"><div class="project-topline"><span class="project-index">PROJECT / ${String(index + 1).padStart(2, '0')}</span><span class="status status-live">${escapeHTML(project.status)}</span></div><h3><a href="projects/${escapeHTML(project.slug)}/">${escapeHTML(project.title)}</a></h3><p>${escapeHTML(project.summary)}</p><div class="tag-row">${tags}</div><div class="project-footer"><div class="project-metric"><strong>${escapeHTML(project.last_updated)}</strong><span>${escapeHTML(project.metric)}</span></div><a class="arrow-link" href="projects/${escapeHTML(project.slug)}/" aria-label="Open ${escapeHTML(project.title)} page">&rarr;</a></div></article>`;
    }).join('');
    projectCards = [...grid.querySelectorAll('[data-project-card]')];
    updateProjects();
  };
  if (grid) fetch('assets/data/projects.json').then((response) => { if (!response.ok) throw new Error(String(response.status)); return response.json(); }).then(renderCatalog).catch(() => { grid.innerHTML = '<p>The generated catalog is temporarily unavailable. Open <a class="text-link" href="research/">the research portfolio</a>.</p>'; });
  searchInput?.addEventListener('input', updateProjects);
  filterButtons.forEach((button) => button.addEventListener('click', () => {
    activeFilter = button.dataset.filter || 'all';
    filterButtons.forEach((candidate) => { candidate.classList.toggle('is-active', candidate === button); candidate.setAttribute('aria-pressed', String(candidate === button)); });
    updateProjects();
  }));
  document.querySelectorAll('[data-sortable-table]').forEach((table) => table.querySelectorAll('th[data-sort-key]').forEach((header, index) => {
    header.tabIndex = 0; header.setAttribute('role', 'button');
    const sort = () => { const tbody = table.querySelector('tbody'); if (!tbody) return; const direction = header.dataset.direction === 'asc' ? 'desc' : 'asc'; table.querySelectorAll('th[data-sort-key]').forEach((item) => delete item.dataset.direction); header.dataset.direction = direction; [...tbody.rows].sort((a, b) => (direction === 'asc' ? 1 : -1) * (a.cells[index]?.textContent.trim() || '').localeCompare(b.cells[index]?.textContent.trim() || '', undefined, { numeric: true })).forEach((row) => tbody.appendChild(row)); };
    header.addEventListener('click', sort); header.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); sort(); } });
  }));
})();
