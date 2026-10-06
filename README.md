# Campus Fleet — Car Rental Management System

A working academic prototype for a University of Ibadan case-study context. This is not an official University service. Fleet records, tariffs and demonstration journeys are synthetic.

## What works

- Registration, login, logout and explicit requester/fleet/finance/manager/administrator roles.
- Date-based vehicle search, booking requests, confirmation, rejection and cancellation.
- Shared rental and maintenance allocations, with database triggers against overlapping active periods.
- Vehicle substitution and rental extension, preserving the agreed daily rate.
- Invoices, unique verified payment references, separate refundable deposits, refunds and additional authorised charges.
- Issue and return inspections, mileage/fuel validation and late-return clearance.
- Rental reconciliation reports with inclusive booking-creation date filters and CSV export.
- Account activation and role changes with reasons, plus an application audit trail.
- SQLite backup command, automated regression tests and an optional GitHub Actions workflow template.

## Requirements

Python 3.12 or newer and an internet connection for initial dependency installation. Tested locally with Python 3.14 and Django 5.2.17 on Windows. SQLite is included with Python. No payment-provider credentials are needed.

## Quick start on Windows

Open PowerShell in this folder and run:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe manage.py migrate
$env:DEMO_PASSWORD = Read-Host 'Choose a private demo password of at least 12 characters'
.venv/Scripts/python.exe manage.py seed_demo
Remove-Item Env:DEMO_PASSWORD
.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8000
```

Alternatively, `./start.ps1` automates the setup and prompts for the password securely. Visit http://127.0.0.1:8000. Demo usernames are `requester`, `fleet`, `finance`, `manager`, and `administrator`. They use the password you selected. The seed command does not reset existing passwords. Change a forgotten password locally with `python manage.py changepassword USERNAME`.

On macOS/Linux, use `python3`, `.venv/bin/python` and `export DEMO_PASSWORD='your-chosen-value'` in place of the corresponding Windows commands. Do not commit a password, database, local secret or environment file.

## Defence walkthrough

1. As **requester**, search dates, choose a vehicle and submit a request with a future collection time.
2. As **fleet**, open the pending request and confirm it with an approval reason. An invoice and allocation are created together.
3. As **finance**, record a verified rental payment and any required deposit with distinct receipt references.
4. As **fleet**, issue the vehicle within its confirmed rental period. Record mileage, fuel percentage and condition.
5. Record its return and inspection. If the return conflicts with another commitment, resolve that commitment, allow turnaround time and record vehicle clearance.
6. As **finance**, return the deposit, reconcile the balance and close the rental.
7. As **manager**, review reconciliation and audit records. As **administrator**, manage account roles; administrator status alone cannot approve rentals or payments.

For a short live demonstration, choose collection a few minutes ahead and return later that day. Do not change system time or misrepresent a demonstration as an operational University rental.

## Tests and evidence

```powershell
.venv/Scripts/python.exe manage.py check
.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
.venv/Scripts/python.exe manage.py test rental --noinput -v 2
```

The suite includes genuine concurrent confirmations on separate database connections, direct database constraint checks, unauthorised access, CSRF, escaped user content, deposit reconciliation, refunds, late-return handling and backup restoration. Test-only MD5 hashing keeps fixtures fast; the application uses Django's normal password hashing. See `docs/test-results.txt` and `docs/VALIDATION.md` for recorded local evidence. The optional `docs/github-actions.yml` template can be placed in `.github/workflows/tests.yml` to enable CI. No remote CI run is claimed.

## Architecture and scheduling

Browser requests pass through Django authentication, CSRF checks and forms to `rental/services.py`. State-changing services run in database transactions and enforce roles on the server. The database stores users, vehicles, bookings, allocations, invoices, charges, payments, refunds, inspections, maintenance and audit events.

Intervals are start-inclusive and end-exclusive. The allocation includes the planned return plus the snapshotted turnaround allowance. The local prototype uses SQLite `IMMEDIATE` transactions to serialise writers before availability reads. Migration `0002_integrity_triggers.py` independently rejects overlap on insert/update and mismatched allocation owners. This is a deliberate implementation adaptation of the report's PostgreSQL proposal. PostgreSQL migration and exclusion constraints are future work; simply changing the database engine is not supported.

The prototype conservatively refuses new reservations while a vehicle awaits physical clearance. A schedule ending does not make an issued vehicle available. Expired but unreleased maintenance also prevents issue. Notifications, institutional identity, live payment gateways, location tracking, utilisation analytics and large-scale load validation are not implemented.

## Financial rules

Billable days equal elapsed hours divided by 24, rounded upward, with a minimum of one day. Confirmation snapshots the vehicle rate, deposit and buffer. Cancellation credits the invoice without deleting its receipts. Refunds link to original receipts and cannot exceed the unrefunded amount. Rental refunds require a credit balance. Deposits do not count as rental receipts. Additional charges require a finance officer's documented reason. The application records payment evidence; it does not move money or independently verify bank transactions.

## Backup and restore

```powershell
.venv/Scripts/python.exe manage.py backup_db backups/rental-2026-10-06.sqlite3
```

The command refuses to overwrite an existing backup and checks database integrity. To restore, stop the server, preserve the current database under a new backup name, copy the chosen verified backup to `db.sqlite3`, run `manage.py check`, restart locally and reconcile booking counts and balances. Restrict database and backup file access. A database administrator can modify the file; the audit trail is not claimed to be tamper-proof.

## Deployment boundary

The default local development mode binds to localhost. Before any real deployment, validate University policy, obtain stakeholder approval, review security, configure HTTPS, set `DJANGO_DEBUG=0`, supply a strong `DJANGO_SECRET_KEY` and set explicit `DJANGO_ALLOWED_HOSTS`. `manage.py check --deploy` checks settings, but is not a security assessment. Use a supported WSGI server such as Waitress behind a trusted HTTPS reverse proxy, serve collected static files, protect backups and run load/recovery tests. Do not expose the development server or seed demonstration accounts on a public service.

## Team

Team leader: **Adedoyin Adeleye (E051358)**.

The team leader's participation statement records equal contributions from Adedoyin Adeleye, Mubinat Muideen (E051387), Solomon Olujide (E051403), Opeyemi Akinfemiwa (E051458), and Adeosun Abiodun (E051481). This statement does not assign invented individual tasks.

## Source and submission materials

The proposal, full writeup and literature archive are separate submission artifacts. Third-party literature is not bundled into this public software repository. The repository contains only source code, project documentation and synthetic test evidence. No University endorsement is implied.
