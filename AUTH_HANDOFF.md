# Authentication Handoff

No credential is stored in this repository.

- GitHub CLI: authenticate interactively with `gh auth login` and select HTTPS unless an SSH workflow is already configured.
- Hugging Face CLI: authenticate interactively with `hf auth login`.
- Never paste tokens into tracked files, deployment commands, screenshots, issues, or logs.
- Configure GitHub Actions with the `HF_TOKEN` repository secret only after rotating any token previously shared in chat.

Current external blocker: explicit authorization is required before creating the new public Hugging Face Space.
