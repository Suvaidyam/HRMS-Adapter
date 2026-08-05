# CLAUDE.md — AI Assistant Guide for `hrmsadapter`

> Read this file **before** touching any code in this app. It describes the real architecture,
> the conventions this codebase already follows, and the rules you must not break. When in doubt,
> **match the existing pattern in the neighbouring file** rather than inventing a new one.

---

## 1. What this app is (context you must hold)

`hrmsadapter` (app title **"HRMS Adapter"**, publisher **Suvaidyam**) is a **mobile middleware adapter** that exposes **ERPNext + Frappe HR** to a **Flutter mobile app** through a versioned REST API. It is a thin layer:

- It **does not own HR data.** Employee, Leave, Expense, Attendance, Payroll, etc. live in `erpnext`/`hrms`. This app reads/writes them through Frappe's ORM.
- It **owns only mobile plumbing:** JWT/refresh tokens, QR desktop-login, device registry, push notifications, API audit logs, and field-mapping/branding config.
- `required_apps = ["erpnext", "hrms"]` — never assume those doctypes are optional.

**Request lifecycle (memorise this):**

```
HTTP request
  → before_request:  decorators.auth.validate_mobile_jwt_if_present   (sets frappe.session.user from Bearer JWT)
  → api/v1/<module>.<fn>   (whitelisted, thin)  →  services/<x>_service   (business logic)  →  utils/response  (envelope)
  → after_request:   utils.audit.log_api_request   (async Mobile API Log)
```

---

## 2. Architecture & layer responsibilities

This is a **strict layered architecture**. Respect the boundaries — do not put business logic in the API layer, and do not build HTTP envelopes inside services.

| Layer          | Location                | Responsibility                                                                 | Rule |
| -------------- | ----------------------- | ------------------------------------------------------------------------------ | ---- |
| **API**        | `api/v1/*.py`           | Whitelisted HTTP endpoints. Parse params, call a service, wrap in `response`.   | Keep **thin**. No JWT logic, no raw SQL, no FCM calls here. |
| **Service**    | `services/*_service.py` | All business logic, ORM access, token/QR/notification logic.                    | Returns **plain Python** (dict/str/None), **never** a response envelope. |
| **Utils**      | `utils/*.py`            | `response` (envelope), `validators` (guards), `audit` (logging).                | Pure helpers. No endpoint-specific logic. |
| **Decorators** | `decorators/auth.py`    | `require_mobile_auth`, `validate_mobile_jwt_if_present`.                         | Auth only. |
| **Doctypes**   | `hrms_adapter/doctype/` | Persistent state: settings, devices, tokens, notifications, logs, mappings.     | Controllers stay minimal. |
| **Tasks**      | `tasks/*.py`            | Scheduled jobs (queue drain, cleanup). Wired in `hooks.py`.                      | Idempotent, exception-safe. |
| **hooks.py**   | root                    | The wiring: `doc_events`, `scheduler_events`, `before/after_request`, retention. | Change deliberately — see §6. |

**Golden rule of a request handler:**

```python
@frappe.whitelist(methods=["GET"])
def get_something(...):
    validators.require_params("x")            # 1. validate
    result = some_service.do_work(...)         # 2. delegate to a service
    return success(data=result)                # 3. wrap in the standard envelope
```

---

## 3. Non-negotiable conventions (follow exactly)

### 3.1 Response envelope — always
Every endpoint returns via `hrmsadapter.utils.response`:

```python
from hrmsadapter.utils.response import success, error, paginated

return success(data={...}, message="optional")
return error("Human message.", "MACHINE_CODE", http_status_code=401)
return paginated(items, total, limit, offset)
```

The envelope shape is a **public contract** the Flutter app depends on:
`{ success, data, message, error, meta.api_version }`. **Do not change its shape or the `api_version` handling.**

### 3.2 Whitelisting & HTTP methods
- Decorate **every** endpoint with `@frappe.whitelist(methods=["GET"|"POST"|"PUT"|"DELETE"])` — always specify the method explicitly.
- Use `allow_guest=True` **only** for the five intentionally-public endpoints: `auth.login`, `auth.refresh_token`, `auth.generate_qr_token`, `auth.poll_qr_status`, `settings.get_branding`. Never add `allow_guest=True` elsewhere without an explicit reason.

### 3.3 Authentication
- Auth is handled globally by `before_request` (`validate_mobile_jwt_if_present`) which sets `frappe.session.user` from a Bearer JWT.
- Inside an authenticated endpoint, the current user is simply `frappe.session.user`; guard with `if frappe.session.user == "Guest": return error(..., 401)` where a hard check is needed.
- JWT claims are available at `frappe.local.mobile_jwt_claims`; device id at `frappe.local.mobile_device_id`.
- **All** token/QR/device logic lives in `services/auth_service.py`. Do not decode JWTs or hash refresh tokens anywhere else.

### 3.4 Settings access
Read config with the cached singleton, never by hardcoding:

```python
settings = frappe.get_cached_doc("HRMS Mobile Settings")
secret = settings.get_password("jwt_secret")   # secrets via get_password, never settings.jwt_secret
```

### 3.5 Validation & employee resolution
Use `hrmsadapter.utils.validators`:
`require_params(...)`, `get_current_employee(user=None)`, `validate_date_range(...)`, `clamp_pagination(limit, offset, max_limit=200)`. Do not re-implement these inline.

### 3.6 Errors
Raise Frappe exceptions inside services (`frappe.throw(msg, frappe.AuthenticationError|ValidationError|DoesNotExistError)`); return `error(...)` from the API layer for expected/handled cases. Match how `auth.py` and `auth_service.py` already do it.

### 3.7 Formatting (ruff — enforced by pre-commit)
- **Tabs** for indentation, **double quotes**, line length 110 (`pyproject.toml`).
- Do not reformat files you aren't editing. Do not convert tabs→spaces.

---

## 4. Naming conventions (match these precisely)

| Thing                       | Convention                                            | Example                                            |
| --------------------------- | ----------------------------------------------------- | -------------------------------------------------- |
| API endpoint path           | `hrmsadapter.api.v1.<module>.<snake_fn>`              | `hrmsadapter.api.v1.leave.get_balance`             |
| Endpoint verbs              | `get_*` (read), `create_*`/`apply`/`checkin` (write), `update_*`, `revoke`/`mark_read` | `create_attendance_request`      |
| Service module              | `<domain>_service.py`, functions are plain verbs      | `auth_service.generate_access_token`               |
| Doc-event handler (service) | `on_<doctype_snake>_<event>`                          | `on_leave_application_submit`                       |
| DocType names               | Prefixed **"Mobile "** (except the settings singleton) | `Mobile Device`, `Mobile Notification`, `HRMS Mobile Settings` |
| DocType folders             | snake_case under `hrms_adapter/doctype/`              | `mobile_field_mapping/`                             |
| Redis keys                  | `mobile_<purpose>:<id>`                               | `mobile_jwt_blacklist:{jti}`                        |
| Response error codes        | UPPER_SNAKE                                            | `AUTH_FAILED`, `DEVICE_NOT_FOUND`                  |

> ⚠️ **Package vs module folder:** the Python package is `hrmsadapter/` (no underscore); the Frappe **module folder** is `hrms_adapter/` (with underscore), and `modules.txt` says `HRMS Adapter`. This asymmetry is correct — never "fix" it.

---

## 5. How to implement common changes (recipes)

### 5.1 Add a new endpoint
1. Find the right `api/v1/<module>.py` (or the closest existing one). Do **not** create a new module unless a genuinely new domain.
2. Write a thin handler: `@frappe.whitelist(methods=[...])` → validate → call a service → `return success(...)`.
3. Put any real logic in the matching `services/<module>_service.py` (create/extend a service function).
4. Reuse `validators`, `response`, and `frappe.get_cached_doc("HRMS Mobile Settings")`.
5. If it returns a list, use `paginated(...)` and `clamp_pagination(...)`.

### 5.2 Add a push-notification trigger for an HR doctype
1. Add the handler function in `services/notification_service.py` named `on_<doctype>_<event>(doc, method=None)`.
2. Wire it in `hooks.py → doc_events` under the target doctype/event.
3. Actual sending goes through the existing `notification_service.send_to_user(...)` / queue → do **not** call FCM directly from the doc-event handler.

### 5.3 Add a scheduled job
1. Add an idempotent, exception-safe function in `tasks/`.
2. Register it under the correct bucket in `hooks.py → scheduler_events` (`all` / `hourly` / `daily`).

### 5.4 Add a new DocType
1. Prefer creating it via the desk with **developer mode ON** so JSON is generated correctly, then `bench migrate`.
2. Name it `Mobile <Thing>`, place it under `hrms_adapter/doctype/`, module **"HRMS Adapter"**.
3. If it needs seeding, extend `install.py` and/or add a patch under `patches/v1_0/` and register it in `patches.txt` (`[post_model_sync]`).
4. If it stores mobile data that should be wiped on uninstall, add it to `before_uninstall` in `install.py`.

### 5.5 Expose an HR field to mobile under a friendly key
Add a **Mobile Field Mapping** row (`doctype_name`, `fieldname`, `mobile_key`) rather than hardcoding aliases — `metadata_service` consumes these.

---

## 6. Do-not-touch / handle-with-care list

These areas break the mobile app or security if changed carelessly. Change only with a clear, explicit reason.

| Area | Why it's sensitive |
| ---- | ------------------ |
| **`utils/response.py` envelope shape / `api_version`** | Public contract; the Flutter client parses this exact structure. |
| **`hooks.py` `before_request` / `after_request`** | Auth (`validate_mobile_jwt_if_present`) and audit run for *every* request. A bug here breaks or unsecures the whole API. |
| **`hooks.py` `doc_events`** | Each entry ties an HR doctype event to a notification. Removing one silently kills notifications. |
| **`services/auth_service.py`** | JWT signing/validation, refresh rotation, blacklist, QR lifecycle, device-limit enforcement. Security-critical. |
| **Secrets** (`jwt_secret`, `fcm_server_key`, `fcm_service_account_json`) | Read via `get_password(...)`. Never log, print, return in a response, or commit. Rotating `jwt_secret` invalidates all live tokens. |
| **`hrms_adapter` folder name & `modules.txt`** | Renaming breaks Frappe module resolution and existing data. |
| **`required_apps`, existing DocType field names** | Renaming a field is a breaking migration for stored data and the mobile app. |
| **`scheduler_events`** | Notification delivery and token/log cleanup depend on these firing. |

---

## 7. Development & debugging workflow

```bash
bench start                                             # web + workers + scheduler
bench --site <site> clear-cache                         # after Python edits that don't hot-reload
bench --site <site> migrate                             # after DocType JSON changes
bench --site <site> run-tests --app hrmsadapter         # tests: tests/test_auth|metadata|settings.py
bench --site <site> console                             # interactive frappe shell
pre-commit run --all-files                              # ruff / eslint / prettier before committing
```

**Debugging checklist:**
- **API failing?** Inspect the **Mobile API Log** DocType (written async by `after_request`) — it records endpoint, method, response code, error type, IP, device.
- **Auth issues?** Confirm the Bearer token, check `frappe.local.mobile_jwt_claims`, and remember the JTI blacklist lives in Redis (`mobile_jwt_blacklist:{jti}`).
- **Notification stuck?** They sit in **Mobile Notification** (`status = Pending`) until the `all` scheduler event `process_notification_queue` drains them — verify the scheduler is running.
- **Server errors:** `frappe.log_error(...)` / the Error Log DocType. Services already wrap risky work in try/except (e.g. `_invoke_hooks`, `audit`).
- Trace end-to-end: `api/v1/<fn>` → the `<x>_service` it calls → the doctype it touches.

---

## 8. Consistency rules (keep the codebase coherent)

- New code must be **indistinguishable in style** from the file next to it: same envelope, same validators, same naming, same tabs/quotes.
- One domain = one API module + (optionally) one service module. Don't scatter a domain's logic across files.
- Every list endpoint paginates the same way (`clamp_pagination` + `paginated`).
- Every write endpoint validates required params first and resolves the employee via `get_current_employee`.
- Keep endpoints thin and services fat — if an API function grows logic, push it into the service.

---

## 9. AI behaviour guidelines (apply to every task here)

1. **Analyze before editing.** Read the target file *and* its service/util collaborators first. Confirm the existing pattern, then extend it.
2. **Avoid unnecessary refactoring.** Do not rename, reformat, reorder, or "clean up" code you were not asked to change. No drive-by rewrites.
3. **Preserve behaviour & contracts.** Never change the response envelope, endpoint paths, DocType field names, or auth flow unless explicitly requested. These are consumed by the live Flutter app.
4. **Keep it modular.** Thin API → service → utils. New logic goes in the correct layer, not wherever is convenient.
5. **Don't break existing functionality.** Assume every endpoint, doc-event, and scheduled task is in use. If a change could affect others, call it out.
6. **Follow existing patterns strictly.** Copy the shape of the nearest sibling (e.g. model a new endpoint on `leave.py`, a new notification trigger on an existing `on_*_submit`).
7. **Respect security.** Never expose or log secrets; keep `allow_guest` minimal; validate input; use `ignore_permissions=True` only where the existing code already does and it is justified.
8. **Verify realistically.** Prefer `bench run-tests --app hrmsadapter` and reading **Mobile API Log** over assumptions. State clearly what you changed and what you did/didn't test.
9. **Ask when ambiguous.** If a request would break a contract in §6 or require a new domain/DocType, surface the trade-off and confirm before proceeding.

---

_Keep this file in sync with reality: if you add a layer, endpoint family, or convention, update the relevant section here so the next AI/developer inherits accurate context._
