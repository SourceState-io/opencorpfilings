## What and why

<!-- The change and the problem it solves. Link the issue. -->

## Checklist

- [ ] `pytest tests` passes offline
- [ ] New behaviour has a test that fails without the change
- [ ] Public names changed? `API.md` regenerated (`python scripts/api_reference.py > API.md`) and the change is compatible with the Stability promise in the README
- [ ] Docs updated (README, `docs/`, `PROVIDER_NOTES.md`) where behaviour changed
- [ ] A new or changed source route: its access terms are recorded in `SOURCE_ACCESS.md`, and any fixture is small and safe to share
- [ ] No credentials, personal data or private paths in code, fixtures or logs
