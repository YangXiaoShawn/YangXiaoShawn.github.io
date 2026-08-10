# AUTH_HANDOFF

Current environment status:

- `gh` is installed and on `PATH`, but no GitHub session is active yet (`gh auth status` shows not logged in).
- `hf` / `huggingface-cli` is installed and logged in with the provided token.
- Network is restricted in this container, so external verification commands may fail unless run in a connected environment.

Recommended follow-up on your machine with network access:

```bash
export PATH="$HOME/.local/bin:$PATH"
gh auth status
# if not logged in:
gh auth login
```

After login, continue with:

1. Initialize repository (if not already).
2. Push to GitHub and enable Pages.
3. Configure external HF dataset/space uploads as needed.
4. Run `python3 scripts/verify_deployment.py` from `GithubIO`.

If you want a clean local reinstall sequence:

```bash
brew install gh
python3 -m pip install --user "huggingface_hub[cli]"
```
