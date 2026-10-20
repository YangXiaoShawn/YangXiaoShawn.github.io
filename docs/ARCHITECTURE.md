# Architecture

## Public surfaces

1. GitHub Pages hosts the static research portal and permanent project pages.
2. GitHub hosts five standalone, reviewable project source repositories; this site keeps no copies of them.
3. The Hugging Face Dataset stores the full versioned research payload without local environments or caches.
4. The Hugging Face Space provides an interactive explorer and reads the Dataset at a configurable revision.

## Repository structure

- `assets/`: shared styles, browser behavior, generated catalog data, and site identity.
- `projects/`: permanent project narratives, research summaries, and each project's site `project.yaml`.
- `apps/space/`: static interactive explorer, compatibility implementation, tests, and runtime metadata.
- `manifests/`: machine-readable inventory, rights, and deployment state.
- `docs/`: governance, security, reproducibility, and release documentation.
- `scripts/`: catalog generation, validation, packaging, deployment, and verification.

## Data flow

1. Each project page owns its site `project.yaml` under `projects/<slug>/`; build inputs from project repositories are fetched at pinned commits by `scripts/project_sources.py`.
2. `scripts/build_site_data.py` generates the browser catalog, section pages, sitemap, and update feed.
3. Compact project repositories receive source, tests, documentation, and public fixtures.
4. Full publishable research content is versioned in the Dataset repository.
5. The Space loads project metadata and representative files from the pinned or configured Dataset revision.

The static site has no server-side state, no analytics by default, and no credential-bearing configuration.
