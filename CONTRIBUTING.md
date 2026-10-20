# Contributing

Thanks for your interest in FocalCove (专注小窝). This project is a prototype and
is maintained on a best-effort basis.

## Development setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# POSIX:   source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python app.py
```

Run the Python tests before sending a change:

```bash
python -m pytest -q
```

Android changes should pass:

```bash
cd android
./gradlew testDebugUnitTest lintDebug
```

## Guidelines

- Keep changes focused and explain the user-visible behavior they affect.
- Match the existing code style and language conventions in the file you edit.
- Add or update tests for behavior changes. Do not weaken an assertion to make a
  test pass.
- Update `THIRD_PARTY_NOTICES.md` when adding a dependency.
- Update `NOTICE` and the relevant `ASSET_NOTICES.md` when adding visual assets.
  Only submit assets you created or that carry a compatible, documented license.
- Never commit `.env`, API keys, keystores, user data, screenshots, evaluation
  samples, build outputs, or deployment records. See `.gitignore`.

## Privacy and security

Do not include real screenshots, personal data, access tokens, or production
hostnames in issues, pull requests, tests, or fixtures. Report vulnerabilities
privately as described in [SECURITY.md](SECURITY.md), not in a public issue.

## Pull requests

- Describe the problem, the approach, and how you tested it.
- Keep the diff reviewable; split unrelated changes.
- By submitting a contribution, you agree that it is licensed under the
  Apache License 2.0, the same license as this project.

## Conduct

Be respectful and constructive. Harassment, discrimination, and disclosure of
another person's private information are not acceptable.
