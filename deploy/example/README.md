# Deployment Example

This directory shows a minimal, self-hosted deployment for the Flask app and the
Android API. Every domain, path, and account is a placeholder. Replace them with
your own values.

## Prerequisites

- A Linux host with Docker Engine and the Compose plugin.
- A DNS name pointing at the host and a TLS certificate for it.
- An existing HTTPS reverse proxy (the example uses Nginx).
- API credentials for one supported vision provider.

## Steps

1. Copy the environment template and fill it in:

   ```bash
   cp deploy/example/.env.production.example deploy/example/.env.production
   chmod 600 deploy/example/.env.production
   ```

   Set `FOCUS_APP_SECRET` to at least 32 random characters, for example:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   Put the vision provider key only in this file. Never embed it in the Android
   client or in front-end code.

2. Build and start the service:

   ```bash
   docker compose -f deploy/example/compose.mobile.yaml up -d --build
   ```

   The Compose file binds the container to `127.0.0.1:8001` only and mounts a
   named volume at `/app/runtime`. The container runs as UID/GID `65534:65534`,
   read-only, with all capabilities dropped.

3. Add the reverse-proxy location blocks from
   [`nginx-mobile-api.conf`](nginx-mobile-api.conf) to your existing HTTPS server
   block. Replace the placeholder domain in the comment with your domain.

   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

4. Verify the minimal health response:

   ```bash
   curl --fail https://your-domain.example/health
   ```

   It should return only `status`, `service`, `api_version`, and `app_version`.

5. Run the optional mobile smoke test with a dedicated test account:

   ```bash
   python scripts/smoke_mobile_api.py \
     --base-url https://your-domain.example/ \
     --username your-test-user
   ```

6. Build the Android client against the same HTTPS origin:

   ```bash
   cd android
   ./gradlew -PFOCUS_API_BASE_URL=https://your-domain.example/ assembleDebug
   ```

## Runtime data

`/app/runtime` holds `users.json`, `mobile_sessions.json`, `user_data/`, and
`user_history/`. Do not bake development accounts or `.env` into the image.
Back up this volume with `scripts/runtime_backup.py` or your usual volume
snapshot tooling.

## Operational notes

- Use exactly one Gunicorn worker. Active sessions live in process memory; multiple
  workers would route requests to the wrong process.
- Keep the container port on loopback or a private Docker network. Do not publish
  it directly to the internet.
- The app trusts one layer of `X-Forwarded-For` and `X-Forwarded-Proto` when
  `FOCUS_TRUST_PROXY_HEADERS=true`. Your proxy must strip client-supplied
  forwarding headers and set its own.
- Rate limiting is process-local. A single instance is required for the built-in
  limits to behave as documented.
- Keeping `FOCUS_EVAL_CAPTURE_ENABLED=false` prevents saving user screenshots.
- This prototype has no CSRF framework and is not hardened for direct public
  exposure. Review [SECURITY.md](../../SECURITY.md) before any public deployment.
