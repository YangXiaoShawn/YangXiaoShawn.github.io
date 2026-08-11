# Automation Gaps

## Current limitations

- The daily workflow validates metadata and packaging but does not refresh external data automatically because no single audited update command exists for both projects.
- Project result pages report validated evidence only; benchmark comparison tables remain incomplete until project-specific result manifests are published.
- Rights review remains a human gate for new third-party raw data.

## Next automation milestones

- Add one deterministic refresh command and output manifest per project.
- Pin Dataset revisions for reproducible Space releases.
- Add project-specific smoke tests before enabling unattended daily data publication.

The workflow scaffold is intentionally non-destructive until these project-level commands are reliable.
