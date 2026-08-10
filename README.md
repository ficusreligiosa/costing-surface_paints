# Surface Paints Backend

Self-hosted PostgreSQL backend that replaces the Google Apps Script / Google
Sheets backend — and, per the role-workflow spec, actually **enforces**
every role's permissions on the server instead of just hiding buttons in
the UI.

## Why it's *almost* a zero-rewrite swap

The old frontend's `gasCall(action, payload)` function always talks the
same way: `GET /exec?data=...` for `loadAll`, `POST /exec` (text/plain
body) for everything else, with a JSON `{action, ...}` payload and a JSON
`{success, ...}` response. This backend's `/api` route speaks exactly that
shape.

The one real change: because permissions are now checked **server-side**
(see "What changed" below), every call after login must carry a session
token. That means two small edits inside the existing `gasCall()` /
`doLogin()` functions — everything else in the 10,000+ line frontend stays
untouched.

```js
// 1. After a successful login, keep the token gasCall returns:
let authToken = '';
// inside doLogin(), after: const result = await gasCall('login', {username:u, password:p});
authToken = result.token;

// 2. gasCall() should attach it to every payload:
const body = JSON.stringify({ action, token: authToken, ...payload });
```

Two flows also now call slightly different actions than before (see
"What changed" — this is intentional, not a shortcut):

- `confirmSudhirDebit()` should call `gasCall('debitInventory', {formulationId, lots, remark})`
  instead of piggy-backing on `saveFormulation`.
- `saveEditBatchCode()` (Amar's flow) should call
  `gasCall('updateBatchNumber', {formulationId, batchNo})` instead of
  `saveFormulation`.

## 1. Install PostgreSQL and create the database

```bash
sudo apt install postgresql
sudo -u postgres psql -c "CREATE USER surface_user WITH PASSWORD 'changeme';"
sudo -u postgres psql -c "CREATE DATABASE surface_paints OWNER surface_user;"
```

## 2. Set up the Python environment

```bash
cd surface-paints-backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit .env with your real DB password
```

## 3. Create tables and seed demo users

```bash
export DATABASE_URL="postgresql://surface_user:changeme@localhost:5432/surface_paints"
python -m app.seed
```

This creates the same demo logins the old system had (admin/admin123,
sudhir/sudhir123, etc.) — but this time passwords are hashed and never sent
to the browser. Change them from the Users page once you're logged in.

## 4. Run the server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For production, run it behind a process manager (e.g. `systemd` or `pm2`)
and a reverse proxy (nginx) with HTTPS.

## 5. Point the frontend at it

In the frontend HTML file, find:

```js
const GAS_URL = 'https://script.google.com/macros/s/.../exec';
```

Replace with:

```js
const GAS_URL = 'https://your-server-address/api';
```

Plus the token wiring described above.

## What changed vs. the old system

Straight from the role-workflow spec's "Notes for the Developer" section —
each point below is a specific gap it called out, and how this backend
closes it.

- **Every permission is now enforced server-side, not just hidden in the
  UI.** The old system's biggest flaw: any logged-in user could open dev
  tools and call the debit function directly, bypassing whatever the UI
  showed them. This backend checks the caller's role against an explicit
  permission table (`ACTION_PERMISSIONS` in `app/actions.py`) before
  running *any* write action — a labentry or batchedit account calling
  `debitInventory` directly gets rejected with an error, not silently let
  through.
- **Inventory debit is a dedicated, one-time-enforced action.** It used to
  be bundled into the generic `saveFormulation` call (with a
  `debitInventory: true` flag). That's now its own action
  (`action_debit_inventory`) that: rejects outright if the formulation was
  already debited, handles the gram/ml → kg conversion, skips (and
  records) any ingredient with insufficient stock instead of failing the
  whole debit, and runs as one atomic database transaction — a failure
  partway through rolls back cleanly instead of leaving inventory
  half-debited.
- **`saveFormulation` can no longer set `inventoryDebited` itself.** In the
  old flow, any formulation edit could theoretically flip that flag. Now
  the field is only ever set inside `action_debit_inventory` — "recipe
  saved" and "inventory debited" are enforced as two genuinely separate
  states, matching the spec's explicit requirement.
- **Amar's batch-code edit is its own restricted action
  (`updateBatchNumber`)** that only ever touches `batch_no` (and
  `product_code`, only if the caller is admin/formulation) — it can't be
  used to sneak in a recipe or cost change.
- **Cost/rate visibility is filtered server-side**, not just hidden by CSS.
  `loadAll` strips every raw-material `rate` and formulation item `rate`
  to `null` for any role outside `{admin, formulation}` before the
  response ever leaves the server — a labentry/batchedit/view/inventory/
  production/report account can inspect network traffic all day and still
  never see a price.
- **Real authentication.** Login happens on the server and returns a
  session token; passwords are hashed with bcrypt and never sent to the
  browser at all — the old system shipped the full user+password list to
  every browser that loaded the page.
- **Real database.** PostgreSQL instead of Google Sheets — no slowdowns as
  data grows, no per-row scanning.
- **Same data model.** Every table mirrors the old `DB` object 1:1
  (`formulations`, `rawMaterials`, `inventory`, `machines`, `shifts`,
  `productionLogs`, etc.) so nothing in the reporting/export logic needs to
  change.

## 6. Open the Admin Panel

A ready-to-use admin panel is included at `admin/index.html` and is served
automatically by the backend at:

```
https://your-server-address/admin/
```

First screen asks for the server address (same `/api` URL as above), your
username, and password — it remembers the server address on that device
after the first login. It talks to the exact same `/api` endpoint and
respects the exact same role permissions as the main app (an inventory or
production login simply won't be able to do anything the backend doesn't
allow them to).

What it covers — the day-to-day master-data tasks a non-technical owner
actually needs, without touching the full production app:

- **Raw Materials** — add/edit/delete, with a low-stock / out-of-stock
  indicator on every row
- **Users** — add/edit/delete logins and roles (the master admin account,
  id 1, can't be deleted — same rule as before)
- **Machines** — add/edit hourly cost and standard capacity
- **Shifts** — add/edit working shifts used in production entries
- **Settings** — packaging cost, the inventory-auto-debit toggle, labour
  rate

Formulations, production logs, and reports are intentionally *not* in this
panel — those are Sudhir Ji / Vivek / Amar's day-to-day tools inside the
main app, not something meant to be edited from an admin screen.

This was built and verified end-to-end with a real headless browser run —
login, add/edit/delete on every tab, and the permission model — before
being included here.

## 7. Migrating real data from the old Google Sheet

`migrate.py` (project root) is a one-time script to pull rows out of the
Sheets CSV exports into this database. It's separate from `app/` on
purpose — it only imports `app.models` / `app.database`, never edits them,
so it can't collide with backend changes.

**Status as of this handoff: waiting on real column headers.** The
`MAPPING` dict at the top of the file has placeholder Sheet column names
(`"Name"`, `"Code"`, `"RmId"`, etc.) based on the frontend's field names —
these are guesses, not confirmed. Do not run `--commit` until they're
replaced with the actual headers from the exported CSVs.

```bash
# 1. Export each relevant Sheets tab as CSV into one folder, e.g.:
#      ./sheets_export/RawMaterials.csv
#      ./sheets_export/Formulations.csv
#      ./sheets_export/Inventory.csv
#      ./sheets_export/StockTransactions.csv
#      ./sheets_export/Machines.csv

# 2. Fix the MAPPING dict in migrate.py to match the real headers.

# 3. Dry run — prints what it WOULD insert, touches nothing:
python migrate.py --source ./sheets_export

# 4. Once the dry-run output looks right:
python migrate.py --source ./sheets_export --commit
```

Sanity-tested against the current models with a fake CSV — a dry run and a
`--commit` both correctly produced a matching `RawMaterial` row. Known gap:
it currently migrates `Formulation` header fields only, not each
formulation's ingredient line items (`FormulationItem` rows) — worth
extending once the real Formulations tab headers are known, since a
formulation without its items isn't very useful on its own.

## Project layout

```
app/
  main.py       — FastAPI app; the /api endpoint + auth/permission dispatch,
                  also serves the admin panel at /admin
  database.py   — SQLAlchemy engine/session
  models.py     — table definitions (incl. the new sessions table)
  actions.py    — one function per action, plus ACTION_PERMISSIONS
  security.py   — password hashing + session token generation
  seed.py       — creates demo users/shifts/settings on first run
admin/
  index.html    — self-contained admin panel (no build step, no dependencies)
migrate.py      — one-time Sheets CSV -> database import (see Section 7)
requirements.txt
.env.example
```

## Tested behaviour

The permission model above isn't just written — it's been run against a
real test suite covering: rejecting unauthenticated calls, cost-field
stripping per role, labentry/batchedit correctly blocked from
`saveFormulation`, a formulation edit unable to sneak in
`inventoryDebited: true`, a real debit correctly deducting stock, and a
second debit attempt on the same formulation being rejected.

## Next steps (not yet built)

- Run the real migration once the Sheet column headers arrive (see Section 7)
- Extend `migrate.py` to also migrate each formulation's ingredient line
  items, not just the header fields
- Session expiry (tokens currently don't expire — fine to ship with, worth
  adding before this sits on the open internet for long)
