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

    siteNav.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', () => {
        navToggle.setAttribute('aria-expanded', 'false');
        siteNav.classList.remove('is-open');
      });
    });

    document.addEventListener('click', (event) => {
      if (!siteNav.contains(event.target) && !navToggle.contains(event.target)) {
        navToggle.setAttribute('aria-expanded', 'false');
        siteNav.classList.remove('is-open');
      }
    });
  }

  document.querySelectorAll('[data-current-year]').forEach((node) => {
    node.textContent = new Date().getFullYear();
  });

  const searchInput = document.querySelector('[data-project-search]');
  const filterButtons = [...document.querySelectorAll('[data-filter]')];
  const projectCards = [...document.querySelectorAll('[data-project-card]')];
  const resultCount = document.querySelector('[data-result-count]');
  const noResults = document.querySelector('[data-no-results]');
  let activeFilter = 'all';

  const updateProjects = () => {
    if (!projectCards.length) return;

    const query = (searchInput?.value || '').trim().toLowerCase();
    let visibleCount = 0;

    projectCards.forEach((card) => {
      const haystack = [
        card.dataset.title,
        card.dataset.field,
        card.dataset.type,
        card.dataset.tags,
        card.textContent,
      ].join(' ').toLowerCase();

      const matchesSearch = !query || haystack.includes(query);
      const matchesFilter = activeFilter === 'all' ||
        card.dataset.field === activeFilter ||
        card.dataset.type === activeFilter ||
        (card.dataset.tags || '').split(',').includes(activeFilter);

      const visible = matchesSearch && matchesFilter;
      card.hidden = !visible;
      if (visible) visibleCount += 1;
    });

    if (resultCount) {
      resultCount.textContent = `${visibleCount} project${visibleCount === 1 ? '' : 's'} shown`;
    }
    if (noResults) {
      noResults.classList.toggle('is-visible', visibleCount === 0);
    }
  };

  searchInput?.addEventListener('input', updateProjects);

  filterButtons.forEach((button) => {
    button.addEventListener('click', () => {
      activeFilter = button.dataset.filter || 'all';
      filterButtons.forEach((candidate) => {
        candidate.classList.toggle('is-active', candidate === button);
        candidate.setAttribute('aria-pressed', String(candidate === button));
      });
      updateProjects();
    });
  });

  updateProjects();

  const toast = document.querySelector('[data-toast]');
  let toastTimer;
  const showToast = (message) => {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('is-visible'), 3000);
  };

  document.querySelectorAll('[data-demo-action]').forEach((element) => {
    element.addEventListener('click', (event) => {
      const action = element.dataset.demoAction;
      if (action === 'download') {
        event.preventDefault();
        showToast('Demo file prepared. Connect this control to your real dataset release.');
      }
      if (action === 'subscribe') {
        event.preventDefault();
        showToast('Demo subscription captured. Connect your preferred email provider here.');
      }
      if (action === 'copy-command') {
        event.preventDefault();
        const command = element.dataset.command || 'make reproduce PROJECT=fama-french-us';
        navigator.clipboard?.writeText(command).then(
          () => showToast('Reproduction command copied.'),
          () => showToast(command),
        );
      }
    });
  });

  const tables = document.querySelectorAll('[data-sortable-table]');
  tables.forEach((table) => {
    const headers = table.querySelectorAll('th[data-sort-key]');
    headers.forEach((header, index) => {
      header.style.cursor = 'pointer';
      header.setAttribute('tabindex', '0');
      header.setAttribute('role', 'button');
      header.setAttribute('aria-label', `Sort by ${header.textContent.trim()}`);

      const sort = () => {
        const tbody = table.querySelector('tbody');
        if (!tbody) return;
        const rows = [...tbody.querySelectorAll('tr')];
        const direction = header.dataset.direction === 'asc' ? 'desc' : 'asc';

        headers.forEach((candidate) => delete candidate.dataset.direction);
        header.dataset.direction = direction;

        rows.sort((a, b) => {
          const aValue = a.children[index]?.dataset.sortValue || a.children[index]?.textContent.trim() || '';
          const bValue = b.children[index]?.dataset.sortValue || b.children[index]?.textContent.trim() || '';
          const numericA = Number(aValue.replace(/[^0-9.-]/g, ''));
          const numericB = Number(bValue.replace(/[^0-9.-]/g, ''));
          let comparison;

          if (!Number.isNaN(numericA) && !Number.isNaN(numericB) && aValue.match(/\d/) && bValue.match(/\d/)) {
            comparison = numericA - numericB;
          } else {
            comparison = aValue.localeCompare(bValue);
          }
          return direction === 'asc' ? comparison : -comparison;
        });

        rows.forEach((row) => tbody.appendChild(row));
      };

      header.addEventListener('click', sort);
      header.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          sort();
        }
      });
    });
  });

  const sections = [...document.querySelectorAll('.article section[id]')];
  const tocLinks = [...document.querySelectorAll('.article-nav a[href^="#"]')];
  if (sections.length && tocLinks.length && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      tocLinks.forEach((link) => {
        const active = link.getAttribute('href') === `#${visible.target.id}`;
        link.style.color = active ? 'var(--accent)' : '';
      });
    }, { rootMargin: '-25% 0px -60% 0px', threshold: [0.05, 0.3, 0.6] });
    sections.forEach((section) => observer.observe(section));
  }
})();
