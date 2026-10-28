# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) for its own releases.

## [2.0] - 2026-10-28

Version bump only. Web and Android share the same 2.0 release number; no scoring,
API, or data-format changes.

### Added

- Web app exposes its version as `APP_VERSION` (`app/config.py`), in the page
  footer, on the usage manual page, and as `app_version` in `GET /health`.

### Changed

- Android `versionName` is now `2.0` (`versionCode 7`).
- `GET /health` keeps `api_version: v1`; the API protocol version and the scoring
  model version (`multidim-v1`) are independent of the app release number.

## [0.6.0] - 2026-10-20

First public release. Earlier internal iterations are not part of the public
Git history.

### Added

- Web application with four-state focus feedback, history, trends, den, and a
  preview-only reward shop.
- Android 10+ client with Compose UI, MediaProjection capture, foreground
  notification, three alert levels, reports, den, and near-black frame detection.
- Shared Python scoring engine with temporal smoothing, confidence shrinkage,
  coverage and reliability markers, and duration recommendation.
- Evaluation tooling for manifest building, model benchmarking, result
  aggregation, timeout comparison, and scoring-policy tuning.
- Apache-2.0 license, NOTICE, third-party notices, security policy, and
  contribution guide.
- Local ECharts 5.4.3 bundle; the Web app no longer loads scripts from a CDN.
- GitHub Actions checks for Python tests, Android unit tests/lint, and Docker.

### Security

- Browser recommendation and history endpoints now require login.
- Generic client error messages replace raw exception text for shop, den, and
  permission failures.
- Browser login and registration are rate limited by client address.
- Templates and health responses no longer expose full runtime snapshots.
- Vision-model logs no longer include goal text or provider error bodies; user
  visible fallback reasons are generic.
- POSIX runtime JSON files are written with `0600` permissions.
- Android debug logging records only method, path, and status; query strings are
  excluded.
- Android capture-problem notifications use a notification ID outside the alert
  range.

### Changed

- Brand-specific shop IDs were replaced with neutral identifiers.
- `META-INF` license resources are no longer stripped from the Android build, and
  license documents ship inside the APK assets.
- Dependencies are pinned. The Dockerfile uses explicit `COPY` paths and a fixed
  Python base image.

### Removed

- Unused SQLite migration code and `DATABASE_PATH`.
- Unused `configure_tesseract` export and an internal placeholder comment.
