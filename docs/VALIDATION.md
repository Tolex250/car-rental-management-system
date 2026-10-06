# Local validation record

Date: 6 October 2026. Environment: Windows, Python 3.14, Django 5.2.17, SQLite.

`python manage.py test rental --noinput -v 2`: **37 tests passed**, zero failures. Runtime reported by the final run: 5.414 seconds. This is not a latency benchmark.

`python manage.py makemigrations --check --dry-run`: no changes detected.

Django system checks: no issues.

Microsoft Edge / Playwright: login, logout, dashboard, fleet catalogue, booking details and reconciliation report visited. Screenshots inspected. Desktop viewport 1440x1000; mobile viewport 390x844. No recorded page-level JavaScript errors or document-level horizontal overflow. Tables can scroll within their containers on small screens.

The test suite covers simultaneous conflicting confirmations, interval boundaries, database trigger insert/update constraints, maintenance conflicts, explicit permissions, record ownership, CSRF, escaped input, login throttling, registration roles, duplicate payments, refunds, deposit reconciliation, saved tariffs, substitutions, cancellation history, issue conditions, late-return clearance and backup restoration.

Test-only password hashing uses MD5 for fast fixture creation; normal application password hashing remains Django's default. The recovery test compares booking, payment, charge and audit rows after restoration and checks SQLite integrity.

These checks establish only observed prototype behaviour. They do not constitute a University pilot, an independent security assessment, formal accessibility certification, a load test or a measurement of operational improvement. GitHub Actions results, when available, are separate from this local record.
