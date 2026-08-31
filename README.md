# HRMS Adapter

> **Mobile middleware adapter for ERPNext HRMS — the API layer that powers the Flutter mobile app.**

HRMS Adapter (`hrmsadapter`) is a [Frappe](https://frappeframework.com/) app that sits **on top of ERPNext + Frappe HR** and exposes a clean, versioned, mobile-friendly REST API. Your ERPNext instance stays the single source of truth; this app is the translation layer between it and a mobile client.

It provides:

- 🔐 **JWT authentication** for mobile (access + refresh tokens), plus **QR sign-in** from the desk
- 📱 **Device management** (register / revoke, max-devices-per-user, FCM tokens)
- 🔔 **Push notifications** (FCM) triggered automatically by HR document events (leave approved, expense submitted, etc.)
- 📊 **Feature-scoped REST endpoints** for attendance, leave, expense, payroll, approvals, dashboard, profile
- 🧩 **Dynamic form metadata** so the mobile app can render forms driven by the backend
- 🔄 **Offline sync** (full / incremental / upload-pending)
- 🎨 **Remote branding & feature flags** — control app colors, logos, and which features are enabled from the desk

---

## Table of Contents

1. [How it fits together](#how-it-fits-together)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration (HRMS Mobile Settings)](#configuration-hrms-mobile-settings)
5. [Folder structure](#folder-structure)
6. [The API in a nutshell](#the-api-in-a-nutshell)
7. [Usage examples](#usage-examples)
8. [Development workflow](#development-workflow)
9. [Build & run commands](#build--run-commands)
10. [Troubleshooting](#troubleshooting)
11. [Contributing](#contributing)
12. [License](#license)

---

## How it fits together

```
┌─────────────────┐        HTTPS / JSON            ┌──────────────────────────────┐
│  Flutter mobile  │  ── Bearer JWT ────────────►  │   HRMS Adapter (this app)      │
│      app         │  ◄── standard envelope ─────  │   /api/method/hrmsadapter.*    │
└─────────────────┘                                │                                │
                                                   │  api/v1  →  services  →  utils │
                                                   └──────────────┬─────────────────┘
                                                                  │ frappe.get_doc / get_list
                                                                  ▼
                                                   ┌──────────────────────────────┐
                                                   │      ERPNext + Frappe HR       │
                                                   │  (Employee, Leave, Expense…)   │
                                                   └──────────────────────────────┘
```

The adapter **never** stores HR data of its own. It reads/writes ERPNext + HR doctypes through Frappe's ORM and adds only the mobile-specific plumbing (tokens, devices, notifications, logs, field mappings).

---

## Prerequisites

You need a working **Frappe Bench** with these apps already available:

| Requirement        | Notes                                                        |
| ------------------ | ------------------------------------------------------------ |
| Frappe Framework   | v15+ (this bench runs v16). Provides `PyJWT`, used for tokens |
| ERPNext            | Required app (`required_apps` in `hooks.py`)                 |
| Frappe HR (`hrms`) | Required app                                                 |
| Python             | ≥ 3.10                                                       |
| MariaDB + Redis    | Standard Frappe stack                                        |

> ℹ️ `erpnext` and `hrms` are **hard dependencies** — Frappe will refuse to install `hrmsadapter` on a site that doesn't have them.

---

## Installation

From your bench directory:

```bash
# 1. Fetch the app into the bench (adds ./apps/hrmsadapter)
bench get-app https://github.com/Suvaidyam/HRMS-Adapter.git --branch develop

# 2. Make sure the site has the required apps first
bench --site your-site.localhost install-app erpnext
bench --site your-site.localhost install-app hrms

# 3. Install the adapter
bench --site your-site.localhost install-app hrmsadapter
```

**What installation does automatically** (see `hrmsadapter/install.py` → `after_install`):

1. Creates the **HRMS Mobile Settings** singleton with safe defaults. No JWT secret is generated or stored — the signing key is derived from the site's `encryption_key`.
2. Seeds **Mobile Field Mapping** rows for common HR fields (e.g. `Leave Application.employee → employee_id`).

Verify it worked:

```bash
bench --site your-site.localhost list-apps        # hrmsadapter should be listed
bench --site your-site.localhost console
>>> frappe.db.exists("HRMS Mobile Settings", "HRMS Mobile Settings")   # 'HRMS Mobile Settings'
```

---

## Configuration (HRMS Mobile Settings)

Almost everything is configured from a **single singleton DocType**: open **HRMS Mobile Settings** in the desk (Awesome Bar → "HRMS Mobile Settings"). No `.env` file is used — configuration lives in the database so it can be changed without redeploying.

| Group             | Fields                                                                                                   | Purpose                                                        |
| ----------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| **Branding**      | `app_name`, `primary_color`, `logo_light`, `company_override`                                             | Remote theming served to the app via `settings.get_branding`  |
| **Store links**   | `app_store_url_android`, `app_store_url_ios`                                                              | Store URLs returned in `get_branding.store_urls`              |
| **Feature flags** | `enable_attendance`, `enable_leave`, `enable_expense`, `enable_payroll`, `enable_approvals`, `enable_checkin`, `enable_offline_sync`, `enable_announcements`, `enable_worklog`, `enable_travel`, `enable_qr_login` | Turn features on/off remotely (`settings.get_feature_flags`). The mobile app hides the entry point *and* blocks the route for anything switched off. `enable_qr_login` is additionally served by the guest `settings.get_branding`, because the QR button is on the login screen and there is no JWT yet |
| **Auth / JWT**    | `jwt_expiry_hours` (24), `refresh_token_expiry_days` (30), `max_devices_per_user` (5), `qr_token_expiry_minutes` (5) | Token lifetimes and device limits (the signing key is derived, not configured) |
| **Push (FCM)**    | `enable_push_notifications`, `fcm_server_key` 🔒, `fcm_project_id`, `fcm_service_account_json`            | Firebase Cloud Messaging credentials                          |
| **Rate limiting** | `enable_rate_limiting`, `rate_limit_per_minute` (60), `rate_limit_auth_per_minute` (10)                   | Abuse protection                                              |

> 🔒 **Never commit or log** `fcm_server_key` or `fcm_service_account_json`. They are stored as encrypted `Password`/`Long Text` fields — read them with `settings.get_password("fcm_server_key")`, not by printing the doc.

### Enabling push notifications

1. Set `enable_push_notifications = 1`, `fcm_project_id`, and
   `fcm_service_account_json` (a Firebase service-account key — Firebase
   Console → Project Settings → Service Accounts → Generate new private key).
   `fcm_server_key` (the legacy server key) is no longer read by the sender —
   see below.
2. Ensure the **scheduler is running** (`bench doctor` / `bench start`) — outgoing notifications are drained by the `all` scheduler event `process_notification_queue`.

> ⚠️ `_send_fcm` sends via FCM's **HTTP v1 API**
> (`fcm.googleapis.com/v1/projects/{project}/messages:send`), authenticating
> with an OAuth2 token minted from `fcm_service_account_json` (via
> `google-auth`). Google fully shut down the legacy
> `fcm.googleapis.com/fcm/send` server-key endpoint in June 2024 — the
> `fcm_server_key` field is kept only for reference and is not used to send
> anything.

---

## Folder structure

```
hrmsadapter/
├── hooks.py                     # ⭐ App wiring: doc_events, scheduler, before/after_request, log retention
├── install.py                   # after_install / before_uninstall (seeds Settings + Field Mappings)
├── modules.txt                  # Module: "HRMS Adapter"
├── patches.txt                  # Migration patches registry
├── pyproject.toml               # Metadata + ruff config (tabs, double quotes, line-length 110)
│
├── api/                         # ── PRESENTATION LAYER ──────────────────────────
│   └── v1/                      #    Versioned, whitelisted HTTP endpoints (thin!)
│       ├── auth.py              #    login, refresh_token, logout, validate_qr_token
│       ├── device.py            #    register / update_app_version / revoke
│       ├── profile.py           #    profile, permissions, profile image
│       ├── attendance.py        #    calendar, checkin, attendance requests, shifts
│       ├── leave.py             #    applications, balance, types, holidays, apply, approve
│       ├── expense.py           #    claims, types, create, submit
│       ├── payroll.py           #    salary slips, slip detail, advances
│       ├── approval.py          #    pending approvals, take_action
│       ├── dashboard.py         #    dashboard data, quick actions
│       ├── notification.py      #    list, mark_read, update_fcm_token, unread_count
│       ├── metadata.py          #    form metadata, doctype states, workflow, link options
│       ├── settings.py          #    branding, feature flags, app config
│       └── sync.py              #    full / incremental / upload_pending
│
├── services/                    # ── BUSINESS LOGIC LAYER ────────────────────────
│   ├── auth_service.py          #    JWT & refresh tokens, device upsert
│   ├── notification_service.py  #    FCM sending + all on_<doc>_<event> handlers + queue
│   ├── metadata_service.py      #    Dynamic mobile form fields (uses Mobile Field Mapping)
│   ├── permission_service.py    #    Module access, approval permission checks
│   └── sync_service.py          #    Offline sync payload assembly
│
├── decorators/
│   └── auth.py                  # require_mobile_auth + validate_mobile_jwt_if_present (before_request)
│
├── utils/                       # ── SHARED HELPERS ─────────────────────────────
│   ├── response.py              #    success() / error() / paginated() envelope  ⭐
│   └── validators.py            #    require_params, get_current_employee, clamp_pagination …
│
├── tasks/                       # ── SCHEDULED JOBS ─────────────────────────────
│   ├── notification_queue.py    #    process_notification_queue (every "all" tick)
│   └── token_cleanup.py         #    expire inactive devices
│
├── hrms_adapter/doctype/        # ── DATA MODEL (note: folder is hrms_adapter) ───
│   ├── hrms_mobile_settings/    #    Singleton config (see above)
│   ├── mobile_device/           #    One row per logged-in device
│   ├── mobile_notification/     #    Outgoing/in-app notification records + retry state
│   └── mobile_field_mapping/    #    Maps internal fieldname → mobile_key alias
│
├── patches/v1_0/                # Data migrations (e.g. create_default_settings)
└── tests/                       # test_auth.py, test_metadata.py, test_settings.py
```

> ⚠️ The Python **package** is `hrmsadapter/` (no underscore) but the **module/doctype folder** is `hrms_adapter/` (with underscore). This is intentional — keep it as-is.

---

## The API in a nutshell

- **Base URL pattern:** `/api/method/hrmsadapter.api.v1.<module>.<function>`
- **Auth:** send `Authorization: Bearer <access_token>` on every authenticated call.
- **Every response** uses one standard envelope (`utils/response.py`):

```json
{
  "success": true,
  "data": { "...": "..." },
  "message": null,
  "error": null,
  "meta": { "api_version": "1.0" }
}
```

On error, `success` is `false`, `data` is `{}`, and `error` is `{ "message": "...", "code": "..." }` with an appropriate HTTP status code.

### Endpoint map (49 endpoints)

| Module     | Endpoints                                                                        |
| ---------- | -------------------------------------------------------------------------------- |
| `auth`     | login, refresh_token, logout, validate_qr_token *(guest)*                        |
| `QR_code_generator` | generate_qr_code *(desk-side; renders the login QR)*                    |
| `device`   | register, update_app_version, revoke                                             |
| `profile`  | get_my_profile, update_profile_image, get_permissions                            |
| `attendance` | get_calendar, checkin, get_attendance_requests, create_attendance_request, get_shifts |
| `leave`    | get_applications, get_balance, get_types, get_holidays, apply, approve           |
| `expense`  | get_claims, get_types, create_claim, submit_claim                                |
| `payroll`  | get_salary_slips, get_slip_detail, get_advances                                  |
| `approval` | get_pending_approvals, take_action                                               |
| `dashboard`| get_dashboard_data, get_quick_actions                                            |
| `notification` | get_notifications, mark_read, update_fcm_token, get_unread_count              |
| `metadata` | get_form_metadata, get_doctype_states, get_workflow, get_link_options            |
| `settings` | get_branding *(guest)*, get_feature_flags, get_app_config                        |
| `sync`     | full_sync, incremental_sync, upload_pending                                      |

*Guest-accessible endpoints (no token needed):* `auth.login`, `auth.refresh_token`, `auth.validate_qr_token`, `settings.get_branding`.

---

## Usage examples

### 1. Login (get tokens)

```bash
curl -X POST 'http://your-site.localhost:8000/api/method/hrmsadapter.api.v1.auth.login' \
  -H 'Content-Type: application/json' \
  -d '{
        "usr": "employee@example.com",
        "pwd": "your-password",
        "device_id": "device-uuid-1234",
        "platform": "Android",
        "app_version": "1.0.0"
      }'
```

Response (`data`):

```json
{
  "access_token": "eyJ...",
  "refresh_token": "…",
  "expires_in": 86400,
  "user": { "email": "employee@example.com", "full_name": "…" },
  "employee": { "name": "HR-EMP-0001", "employee_name": "…", "department": "…" }
}
```

### 2. Call an authenticated endpoint

```bash
curl 'http://your-site.localhost:8000/api/method/hrmsadapter.api.v1.leave.get_balance' \
  -H 'Authorization: Bearer eyJ...'
```

### 3. Refresh an expired access token

```bash
curl -X POST '.../hrmsadapter.api.v1.auth.refresh_token' \
  -H 'Content-Type: application/json' \
  -d '{ "refresh_token": "…", "device_id": "device-uuid-1234" }'
```

### 4. QR login (high level)

1. Desk user opens **HRMS Mobile Settings**, whose client script calls
   `QR_code_generator.generate_qr_code`. That mints a token, parks
   `{user, company, name}` in Redis under `hrms_mobile_token:{token}` for
   `qr_token_expiry_minutes`, and returns a base64 PNG of
   `{"server_url": …, "token": …}`.
2. The mobile app scans it and posts the token to `auth.validate_qr_token`
   (guest) together with its `device_id` and device metadata.
3. The endpoint redeems the Redis key — deleting it immediately, so a token is
   single-use — upserts the Mobile Device row and returns the usual
   access/refresh token pair.

> The QR carries the session of **whoever generated it**, so the phone signs in
> as that desk user. There is no separate desktop-approval handshake; the
> DocType-backed one was removed.

---

## Development workflow

```bash
# Start the dev server (web + workers + scheduler)
bench start

# After editing Python: usually auto-reloads. If not:
bench --site your-site.localhost clear-cache

# After adding/editing a DocType JSON manually (outside the UI):
bench --site your-site.localhost migrate

# Run this app's tests
bench --site your-site.localhost run-tests --app hrmsadapter
```

- Develop with **developer mode ON** so DocType changes are written back to JSON:
  `bench --site your-site.localhost set-config developer_mode 1`
- **Notifications & scheduled cleanup** only run when the **scheduler/worker** is alive (`bench start` runs them; `bench doctor` checks them).

---

## Build & run commands

| Task                         | Command                                                       |
| ---------------------------- | ------------------------------------------------------------ |
| Fetch app                    | `bench get-app <repo-url> --branch develop`                  |
| Install on site              | `bench --site <site> install-app hrmsadapter`                |
| Build JS/CSS assets          | `bench build --app hrmsadapter`                              |
| Apply schema / patches       | `bench --site <site> migrate`                                |
| Run dev server               | `bench start`                                                |
| Run tests                    | `bench --site <site> run-tests --app hrmsadapter`            |
| Lint & format (pre-commit)   | `pre-commit run --all-files` (ruff / eslint / prettier)      |
| Uninstall (dev)              | `bench --site <site> uninstall-app hrmsadapter`              |

---

## Troubleshooting

| Symptom                                                    | Likely cause & fix                                                                                                             |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `install-app hrmsadapter` fails with a required-app error  | Install `erpnext` and `hrms` on the site **first** (they are declared in `required_apps`).                                    |
| Every request returns `401 Authentication required`        | Missing/expired/invalid `Authorization: Bearer <jwt>`. Get a fresh token via `auth.login` or `auth.refresh_token`.           |
| `Token has been revoked`                                   | The JTI is blacklisted in Redis (user logged out / device revoked). Log in again.                                            |
| `No active Employee record found for the current user`     | The logged-in User isn't linked to an **Active** Employee (`Employee.user_id`). Link it in the desk.                          |
| Push notifications never arrive                            | Check `enable_push_notifications`, FCM credentials, and that the **scheduler/worker is running** (queue drainer is a job).    |
| Notifications stuck in `Pending`                            | The `all` scheduler event isn't firing → run `bench start` / verify `bench doctor`; queue is drained by `process_notification_queue`. |
| Changed a DocType JSON but the field isn't there           | Run `bench --site <site> migrate` and `clear-cache`.                                                                          |
| Tokens fail after restoring a DB onto another site         | The signing key follows the site's `encryption_key` — copy the original `site_config.json` key, or have clients log in again. |
| Too many devices / can't log in on a new phone            | `max_devices_per_user` (default 5) reached — the oldest device is auto-expired on next login, or revoke one manually.        |

---

## Contributing

This app uses `pre-commit` for formatting and linting. [Install pre-commit](https://pre-commit.com/#installation) and enable it:

```bash
cd apps/hrmsadapter
pre-commit install
```

Configured tools: **ruff** (Python lint/format — tabs, double quotes, line-length 110), **eslint**, **prettier**, **pyupgrade**.

**Before opening a PR:** run `pre-commit run --all-files` and `bench --site <site> run-tests --app hrmsadapter`.

---

## License

MIT — see [license.txt](license.txt). © Suvaidyam.
