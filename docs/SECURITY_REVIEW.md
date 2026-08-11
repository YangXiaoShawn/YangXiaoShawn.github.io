# Security Review

## Findings

- No GitHub token, Hugging Face token, private-key marker, or credential-bearing environment file was detected in the public `GithubIO` tree.
- API credential references in the Macroeconomics adapters are environment-variable names and guarded configuration, not embedded values.
- The first full Dataset snapshot included local `.venv`, test caches, and operating-system metadata. These are non-research artifacts and are removed in the cleanup revision.
- Public documentation no longer contains an absolute local home-directory path.

## Controls

- Root and project `.gitignore` rules exclude local environments, caches, `.env*`, editor state, and system metadata.
- CI uses `HF_TOKEN` only as a secret and does not interpolate it into logs.
- Live data adapters require explicit authorization and retrieve credentials from environment variables.
- Dataset and Space releases are versioned, so cleanup commits remain recoverable.

## Rotation note

Any token ever pasted into chat or exposed in terminal history should be treated as compromised and revoked at its provider. Replacement credentials must be stored only in the provider CLI/keychain or a secrets manager.
