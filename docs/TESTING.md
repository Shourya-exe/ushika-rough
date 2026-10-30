# USHIKA: Testing guide

Four layers, from fastest to most real:

1. **Automated tests.** No network, about 1 second, run on every change.
2. **Postman, simulating Meta.** Signed fake webhooks and real API calls against your running server.
3. **Manual webhook simulation.** Sign a payload yourself with a few lines of Python.
4. **Real Meta test number.** The end-to-end proof required by the definition of success.

## 1. Automated tests

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python manage.py test whatsapp            # all 51 tests
python manage.py test whatsapp.tests.test_media -v 2   # one area, verbose
```

The tests run against an in-memory test database. They use a temporary `MEDIA_ROOT` (deleted afterwards) and fixed test credentials, so `.env` doesn't matter. Calls to Meta are faked with the [`responses`](https://github.com/getsentry/responses) library. Tests that exercise HTTP run inside a `RequestsMock`, which raises on any request that wasn't registered, so no test reaches the network.

| File | Covers |
|---|---|
| `test_webhook.py` | Handshake (correct, wrong and unconfigured token; bad mode; missing challenge). Signatures (missing, wrong secret, tampered body, no secret configured). Invalid JSON. Event storage. Identical redelivery reported as `duplicate`. Processing failure still returns 200, is recorded, and is replayed by `reprocess_webhooks`. Redelivery of a failed event. Non-message fields ignored. |
| `test_processing.py` | Text message → contact and message fields. Profile-name updates. Same `wamid` in another envelope stored once. Malformed entries skipped. Body extraction for interactive, location, reaction and button. Reply context. Unsupported type keeps Meta's error. Statuses advance and never go backwards. Failed status stores the error. Duplicate status ignored. Unknown status values. Orphan status linked after a send. |
| `test_media.py` | Image downloaded and stored (path, bytes, size, Bearer token on both calls). Document filename sanitised (`../../`). Base64 SHA-256 accepted. Hash mismatch → failed with no file. Size limit, both declared and while streaming. HTML error page rejected. Failed download recovered through the save endpoint. Disabled type → `skipped` with no HTTP call. Retry command respects the attempt cap. Sticker and voice-note extensions. Save rules: nothing fetched on arrival by default; image saved on request when the level allows it; images and PDFs allowed separately; no level → refused even for a superuser; audio and Word files superuser-only; only `application/pdf` documents count as PDFs; download on arrival follows the same rules; the retry command honours the level. Admin file access: a superuser previews and downloads unsaved files with nothing stored; other users get 404; saved files preview from storage; HTML, SVG, XML and unknown types are never inline; Meta failures → 502 with the attachment unchanged; `download_url` and `preview_url` follow the user; admin pages show previews and links without calling Meta. |
| `test_api.py` | 401 without a token on every endpoint. Token endpoint. Log in, then `auth/me/` names the user. Wrong password and bad token rejected. Health is public. List, filter, search, ordering and paging of messages. Detail includes attachments and status history. Contact counts, level and level filter. File download headers and bytes. 404 for not-downloaded files. OpenAPI schema. Send text (exact payload to Meta), template, document. Meta rejection → 502 and stored as failed. Idempotency key → one call to Meta. Ten validation-error cases. |

Payload builders that mirror Meta's webhook shapes live in `whatsapp/tests/helpers.py` (`envelope`, `text_message`, `image_message`, `document_message`, `status_entry`, `mock_media`). Use them in new tests.

Other checks worth running before a release:

```powershell
python manage.py makemigrations --check --dry-run          # no model change without a migration
python manage.py spectacular --validate --fail-on-warn --file schema.yml
$env:DJANGO_DEBUG="false"; python manage.py check --deploy  # needs DJANGO_SECRET_KEY + ALLOWED_HOSTS
```

## 2. Postman

**Setup**
1. Import `postman/USHIKA.postman_collection.json`.
2. Set the collection variables:

| Variable | Value |
|---|---|
| `base_url` | `http://127.0.0.1:8000`, or your tunnel URL |
| `username` / `password` | A Django user (`createsuperuser`) |
| `app_secret` | **Exactly** your `WHATSAPP_APP_SECRET` (used to sign simulated webhooks) |
| `verify_token` | Your `WHATSAPP_VERIFY_TOKEN` |
| `customer_wa_id` | Your verified test phone, digits only (e.g. `447700900123`) |
| `phone_number_id` | Your `WHATSAPP_PHONE_NUMBER_ID` (informational) |

3. Run **0. Setup → Obtain API token**. It stores `api_token`, which every API request uses as `Authorization: Token …`.

**Folders**

| Folder | Scenarios |
|---|---|
| 0. Setup | Health check; obtain token; check login (`auth/me/`) |
| 1. Webhook (simulate Meta) | Handshake (good and wrong token); inbound text, image, document, button reply; duplicate delivery (send it twice, and the second answer is `duplicate`); `delivered`, `read` and `failed` statuses for your last sent message; forged signature → 403 |
| 2. Messages | List, filter, search, time window, detail, status history; send text, `hello_world` template, image by link, reply to the last inbound; idempotent retry (send twice); validation error |
| 3. Contacts | List and search |
| 4. Attachments | List, failed only, detail, download (use **Send and Download**), preview, save (contact level rules) |
| 5. Delivery statuses | List; filter by the last sent `wamid` |

**How the webhook signing works.** The *1. Webhook* folder's pre-request script does three things:
- sets fresh `wamid`, `media_id` and `now_ts` values on every request, so simulated messages aren't treated as duplicates;
- resolves the body's `{{variables}}`;
- adds `X-Hub-Signature-256: sha256=HMAC_SHA256(body, app_secret)`, exactly as Meta does.

If `app_secret` doesn't match the server, these requests get **403**, which is the signature check working.

**What to expect without real Meta credentials**
- Simulated inbound image and document messages create attachments that end up `failed`, because the media ids are made up or there's no access token. That's correct behaviour. Use **4. Attachments → Retry download** after a real inbound message instead.
- Sends return **502** with the error stored on the message (for example `WHATSAPP_ACCESS_TOKEN is not configured`, or a Meta error code).

**Suggested run order:** 0 → 1 (text, image, duplicate twice, forged) → 2 (list, send template) → 1 (statuses, which use the last sent `wamid`) → 4 → 5. The collection can also run headless with Newman: `npx newman run postman/USHIKA.postman_collection.json --env-var ...`. The collection itself has not yet been run in Postman or Newman (see [TASKS.md](TASKS.md)).

## 3. Manual webhook simulation

To post a hand-written payload, sign the exact bytes you send:

```python
# sign_and_send.py   usage: python sign_and_send.py payload.json
import hashlib, hmac, os, sys, requests
body = open(sys.argv[1], "rb").read()
secret = os.environ["WHATSAPP_APP_SECRET"].encode()
sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
r = requests.post("http://127.0.0.1:8000/webhooks/whatsapp/", data=body,
                  headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig})
print(r.status_code, r.text)
```

A minimal payload (`payload.json`):
```json
{"object": "whatsapp_business_account",
 "entry": [{"id": "WABA_ID", "changes": [{"field": "messages", "value": {
   "messaging_product": "whatsapp",
   "metadata": {"display_phone_number": "15550001111", "phone_number_id": "PHONE_NUMBER_ID"},
   "contacts": [{"profile": {"name": "Test User"}, "wa_id": "16315551234"}],
   "messages": [{"from": "16315551234", "id": "wamid.MANUAL1", "timestamp": "1761600000",
                 "type": "text", "text": {"body": "hello"}}]}}]}]}
```

**Signature checks to try**
- Send without the header → 403.
- Change one byte after signing → 403.
- Sign with another secret → 403.
- Send the same file twice → `ok`, then `duplicate`.

Meta also has a **Test** button next to each webhook field in the app dashboard (**WhatsApp → Configuration**). It sends sample payloads to your registered URL, signed with your real app secret.

## 4. Real Meta test-number checks

This is the end-to-end proof from the PRD. Prerequisites:
- `.env` has a real `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET` and `WHATSAPP_VERIFY_TOKEN`.
- Your phone is a verified recipient of the test number.

1. **Run and expose:** `python manage.py runserver`, then `cloudflared tunnel --url http://127.0.0.1:8000`. Add the tunnel host to `DJANGO_ALLOWED_HOSTS` and restart.
2. **Register the webhook:** in Meta, open **WhatsApp → Configuration → Edit**. Set the callback to `https://<tunnel>/webhooks/whatsapp/` and the verify token to yours, then **Verify and save**. Expect the log line `Webhook subscription verified`. **Subscribe** to `messages`.
3. **Outbound template:** `POST /api/v1/messages/send/` with `{"to": "<your phone>", "type": "template", "template_name": "hello_world", "language_code": "en_US"}`.
   - [ ] 201 with a `wa_message_id`
   - [ ] the message arrives on the phone
   - [ ] `GET /api/v1/messages/{id}/` shows `sent` and then `delivered`; open the chat and it becomes `read`
4. **Inbound text:** reply "hi" from the phone.
   - [ ] `GET /api/v1/messages/?direction=inbound` lists it with your profile name
   - [ ] a `WebhookEvent` with status `processed` appears in the admin
5. **Outbound free-form:** within 24 hours of step 4, send `{"type": "text", "text": "…"}` (optionally with `reply_to` set to the inbound `wamid`).
   - [ ] it arrives, quoted if `reply_to` was set
6. **Inbound image:** in the admin, give your contact a level that allows images and PDFs (**Contact levels**, then the **Level** column under **Contacts**). Send a photo with a caption, then `POST /api/v1/attachments/{id}/save/`.
   - [ ] before the save the attachment is `skipped`; after it, `downloaded`, the file is under `storage/whatsapp/YYYY/MM/<media_id>/`, and `GET …/download/` returns the image
   - [ ] before the save, a superuser can see the image under **Media attachments** in the admin, and it is still `skipped` with nothing under `storage/`
7. **Inbound document:** send a PDF and save it.
   - [ ] downloaded with its original (sanitised) filename
   - [ ] with *can save PDFs* unticked, the save returns 403 and nothing is stored
   - [ ] even then, a superuser can read the PDF in the admin's preview and download it
8. **Failure paths:**
   - [ ] a send to an unverified number → 502 with `error_code` 131030
   - [ ] a free-form text more than 24 hours after the last inbound → `failed` (131047), via webhook or 502
   - [ ] a forged webhook (Postman *Invalid signature*) → 403 against the tunnel URL
9. **Retry:** temporarily set a wrong `WHATSAPP_ACCESS_TOKEN`, send an image from the phone, and see `failed`. Restore the token and run `POST /api/v1/attachments/{id}/save/` → `downloaded`.

Record the date, Graph API version and results in [TASKS.md](TASKS.md) when done.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Meta: "The callback URL or verify token couldn't be validated" | Server not reachable through the tunnel, host missing from `DJANGO_ALLOWED_HOSTS` (Django returns 400), or verify-token mismatch |
| Every webhook POST → 403 | `WHATSAPP_APP_SECRET` empty or not the app's secret (App settings → Basic) |
| Messages arrive in Meta but not in USHIKA | `messages` field not subscribed, or the app isn't subscribed to the WABA |
| Send → 502, code `190` | Access token expired (temporary tokens last about 24 h) |
| Send → 502, code `131030` | Recipient not on the test number's allowed list |
| Send → 502, code `131047` | Outside the 24-hour window; send a template |
| Send → 502, code `132001` | Template name or language doesn't exist or isn't approved |
| Send → 502, code `100` | Invalid parameter (check `to`, `type`, media link reachability) |
| Dashboard **Test** webhook arrives, real messages never do | The app isn't subscribed to the number's WhatsApp Business Account (the WABA id is in `GET /{phone-number-id}?fields=health_status`). Check `GET /{WABA_ID}/subscribed_apps` and subscribe with `POST /{WABA_ID}/subscribed_apps` using the app's access token |
| Attachment `failed`: "HTML page instead of the media file" | Expired media URL or wrong token; retry |
| Attachment `failed`: "SHA-256 … does not match" | Corrupted or partial download; retry |
| Webhook took long, Meta retried | Large inline media download; enable `USE_CELERY` |
