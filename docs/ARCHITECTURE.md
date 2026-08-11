# Architecture

## Public surfaces

1. GitHub Pages hosts the static research portal and permanent project pages.
2. Two standalone GitHub repositories host compact, reviewable project source packages.
3. The Hugging Face Dataset stores the full versioned research payload without local environments or caches.
4. The Hugging Face Space provides an interactive explorer and reads the Dataset at a configurable revision.

## Repository structure

- `assets/`: shared styles, browser behavior, generated catalog data, and site identity.
- `projects/`: permanent project narratives and research summaries.
- `casuallab/`, `macroeconomics/`: upload-ready public project copies.
- `apps/space/`: Gradio application, tests, and runtime metadata.
- `manifests/`: machine-readable inventory, rights, and deployment state.
- `docs/`: governance, security, reproducibility, and release documentation.
- `scripts/`: catalog generation, validation, packaging, deployment, and verification.

## Data flow

1. Each project owns its canonical `project.yaml`.
2. `scripts/build_site_data.py` generates the browser catalog, section pages, sitemap, and update feed.
3. Compact project repositories receive source, tests, documentation, and public fixtures.
4. Full publishable research content is versioned in the Dataset repository.
5. The Space loads project metadata and representative files from the pinned or configured Dataset revision.

The static site has no server-side state, no analytics by default, and no credential-bearing configuration.
