# USHIKA: Security

USHIKA handles personal data: phone numbers, names, message content and customer files. It also holds credentials that can send WhatsApp messages as the business. This document covers how both are protected, and what still has to be done before production.

## Secret management

| Secret | Where it lives | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | env / `.env` | Required when `DJANGO_DEBUG=false`; the app refuses to start without it. Rotating it invalidates sessions. |
| `WHATSAPP_ACCESS_TOKEN` | env / `.env` | Can send messages and read media as the business. |
| `WHATSAPP_APP_SECRET` | env / `.env` | Lets anyone holding it forge webhooks. |
| `WHATSAPP_VERIFY_TOKEN` | env / `.env` | Low value (only gates the handshake), but keep it random. |
| `POSTGRES_PASSWORD` | env | Production database. |
| DRF API tokens | database (`authtoken_token`) | One per user; revoke by deleting it in the admin. |

**Rules**
- `.env` is git-ignored. Only `.env.example` (no values) is committed. Never paste real secrets into docs, tickets, Postman exports or logs.
- In production, inject secrets from the platform's secret store (environment variables or a secrets manager), not from a file on the server.
- **Access tokens:** Meta's temporary token expires after about 24 hours. For longer use, create a **System User** in Business Settings and generate a token with only `whatsapp_business_messaging` and `whatsapp_business_management`, assigned to this app and WABA only. Rotate it on a schedule, and immediately if it may have leaked. Rotating the token or app secret is an env change plus a restart.
- Settings read secrets at call time. Nothing secret is cached in module globals or written to the database.

## Webhook security

1. **Signature validation.** Every POST must carry `X-Hub-Signature-256: sha256=<hex>`, the HMAC-SHA256 of the **raw request body** keyed with the app secret.
   - Computed on raw bytes, before JSON parsing.
   - Compared with `hmac.compare_digest` (constant-time).
   - Missing header, wrong prefix, wrong secret or modified body → 403, and nothing is stored.
   - **Fail closed:** if `WHATSAPP_APP_SECRET` is empty, every POST is rejected. There is deliberately no "skip verification" switch.
2. **Verify-token handshake.** Constant-time comparison; an unconfigured token rejects all handshakes.
3. **CSRF** is exempted only on the webhook view (Meta can't send a CSRF token). The signature takes its place.
4. **Replay and duplicates.** Deliveries are idempotent (body hash, `wamid`, status triple), so a replayed genuine payload creates nothing new. Payload timestamps are not used to reject old replays; any replay must still carry a valid signature, which requires the secret.
5. **Information leakage.** Error responses are short fixed strings. Stack traces never reach Meta (DEBUG must be off in production).

## API authorization

- Every `/api/v1/` endpoint requires authentication (`IsAuthenticated` by default). Supported: `Authorization: Token <key>` and Django session (admin login).
- `POST /api/v1/auth/token/` exchanges a username and password for the user's token. Use strong passwords; Django's password validators are on. `GET /api/v1/auth/me/` returns the user a token belongs to, which is how a client checks its login.
- **Authorization is coarse:** any authenticated user can read all conversations and send messages. The one finer rule covers saving media: images and PDFs only when the contact's level allows it, other media only by a superuser (see [API.md](API.md#saving-media-contact-levels)). Previewing or downloading a file that isn't saved is superuser-only and ignores the level, because nothing is kept (see [API.md](API.md#previewing-and-downloading)). That's acceptable for an internal POC with a few trusted operators. Before more users or external clients get access, add per-client scopes or permissions (see open questions in [PRD.md](PRD.md)).
- Outbound sends record `sent_by` (the API user) for accountability.
- API docs (`/api/schema/`, `/api/docs/`) are public only in DEBUG. In production they require a staff user.
- **The Django admin has full access.** Grant `is_staff` sparingly, use strong passwords, and consider restricting `/admin/` by network in production.
- TLS: tokens and data must only cross HTTPS in production (see [Deployment security](#deployment-security)).

## File validation and handling

Incoming media comes from customers, so treat it as untrusted.

| Control | Implementation |
|---|---|
| Type allowlist | Files are saved on request only. Images and PDFs need a contact level that allows them; audio, video, stickers and other documents need a superuser. A PDF is a `document` whose MIME type (as reported by WhatsApp) is `application/pdf`; file contents are not inspected. On-arrival download (`WHATSAPP_DOWNLOAD_MEDIA=true`) follows the same rules, limited to `WHATSAPP_MEDIA_TYPES` |
| Size limit | `WHATSAPP_MEDIA_MAX_BYTES` (100 MB default), checked against Meta's declared size **and** while streaming |
| Integrity | SHA-256 of the bytes must match Meta's reported hash (hex or base64), or the file is discarded |
| Error pages | An HTML response when media was expected is rejected |
| Filenames | Sender filenames are reduced to a safe basename (`get_valid_filename`, path separators stripped, length capped). Paths are `whatsapp/YYYY/MM/<media_id>/<name>`, and existing files are never overwritten. |
| No public serving | No `MEDIA_URL` route. Files leave only through the authenticated download and preview endpoints. Downloads are `Content-Disposition: attachment`, so browsers save rather than render them. |
| Inline previews | Previews run on the app's origin, in the session of a logged-in user, so a customer's HTML or SVG file could otherwise act as that user. Only the types in `media.PREVIEW_MIME_TYPES` are served inline (PDF, plain text, raster images, audio, video). The `Content-Type` comes from that allowlist, and `X-Content-Type-Options: nosniff` (Django `SecurityMiddleware`) stops browsers from reinterpreting the bytes. Everything else is download-only. Previews can be framed by the same origin only. |
| Storage location | `MEDIA_ROOT` (default `./storage`) must not be inside a web server's static root |

**Not yet done (recommended before production):**
- malware scanning (for example ClamAV or a cloud scanning service) before files are offered for preview or download;
- content-type sniffing to confirm the bytes match the declared MIME type;
- encryption at rest for the storage volume or bucket.

## Privacy

- **Data collected:** WhatsApp ID (phone number), profile name, message content and metadata, raw webhook payloads, media files, delivery statuses. Nothing else.
- **Purpose limitation:** data is used to run the customer conversation and the integration. Don't reuse it for unrelated purposes without a legal basis.
- **Minimisation:** raw payloads are stored for audit and replay. If that's not needed, consider clearing `WebhookEvent.payload` and `Message.payload` after processing (see retention).
- **Subject requests:** to export or delete a person's data, find the `Contact` by `wa_id`, then their `Message`s, `MediaAttachment` files and matching `WebhookEvent`s. Deleting a contact is blocked while messages exist (`PROTECT`), so delete messages first; attachments and status events cascade. Uploaded files must be deleted from storage too (deleting the row doesn't remove the file).
- Follow WhatsApp Business policies and local data-protection law (GDPR, Kenya's DPA, India's DPDP Act, etc., depending on where you operate). Get opt-in consent before messaging customers proactively.

## Logging rules

- **Logged:** event and record ids (`wamid`, primary keys, media ids), message type, status transitions, Meta error codes and messages, signature or verify-token rejections, download failures with reasons.
- **Never logged:** access tokens, app secret, verify token, API tokens, `Authorization` headers, message text, captions, phone numbers, file contents. The code follows this; keep it that way in reviews.
- Django's request logging (`django.request`) records the paths of 4xx/5xx responses. Webhook and API paths contain no personal data, though query strings on list endpoints may (for example `?wa_id=`).
- In production, ship logs to a store with restricted access and a retention limit.

## Data retention

There is **no automatic purge yet**. Everything is kept until deleted. Before production, agree on a policy, for example:

| Data | Suggested retention |
|---|---|
| `WebhookEvent` (raw payloads) | 30 days, or clear `payload` after successful processing |
| Messages and status events | Business requirement (e.g. 12–24 months) |
| Media files | Shortest period that meets the business need (e.g. 90 days), then delete file and row |
| Failed / skipped attachments | 30 days |

Implement it as a management command run on a schedule (cron or Celery beat), and include storage files, not only database rows. Backups must follow the same policy.

## Deployment security

Production checklist:

- [ ] `DJANGO_DEBUG=false` and a strong, unique `DJANGO_SECRET_KEY`.
- [ ] `DJANGO_ALLOWED_HOSTS` lists only real host names; `DJANGO_CSRF_TRUSTED_ORIGINS` is set for the admin's HTTPS origin.
- [ ] HTTPS everywhere. TLS terminates at the proxy, which sets `X-Forwarded-Proto` (honoured through `SECURE_PROXY_SSL_HEADER`). With DEBUG off, the settings enable `SECURE_SSL_REDIRECT`, secure cookies and HSTS (`DJANGO_SECURE_HSTS_SECONDS`, default 3600). Enable `..._INCLUDE_SUBDOMAINS` / `..._PRELOAD` only when every subdomain is HTTPS.
- [ ] `python manage.py check --deploy` is clean, apart from consciously accepted HSTS warnings.
- [ ] PostgreSQL with a dedicated least-privilege user, TLS to the database, and encrypted backups.
- [ ] Media on a persistent, access-controlled volume or a **private** bucket (never public-read), with backups.
- [ ] Secrets from a secret store, and a permanent System User token scoped to this WABA.
- [ ] Redis (if `USE_CELERY`) not exposed publicly; password or TLS enabled.
- [ ] gunicorn runs as a non-root user; only the proxy is publicly reachable.
- [ ] Admin access restricted (strong passwords, few staff, network restriction if possible).
- [ ] Dependency updates: re-run tests after `pip install -U`; watch Django and DRF security releases. Django 5.2 is supported until April 2028.
- [ ] The Graph API version in `WHATSAPP_API_VERSION` is still supported (Meta versions last about 2 years).
- [ ] Rate limiting at the proxy for `/api/v1/auth/token/` and `/webhooks/`.

## Threat summary

| Threat | Mitigation |
|---|---|
| Forged webhook injecting fake messages | HMAC signature with the app secret; fail closed |
| Replay of a captured webhook | Idempotent processing; needs a valid signature anyway |
| Stolen API token | HTTPS only; revoke the token; per-user tokens; `sent_by` audit |
| Brute-forcing the token endpoint | Strong passwords; proxy rate limiting (to add) |
| Malicious file from a customer | Size limit, hash check, safe names, inline previews only for types that can't run scripts on our origin; malware scanning still to add |
| Path traversal via filename | Basename sanitisation; storage paths built from ids |
| Leaked Meta token | Env-only storage; System User token with minimal scopes; rotation |
| Data exposure in logs | Ids-only logging rules |
| Unbounded data growth or retention breach | Retention policy and purge command (to add) |

## Reporting a vulnerability

Report suspected vulnerabilities privately to the project owner, not in a public issue. Include steps to reproduce. Rotate any credential that may have been exposed before investigating further.
