# 03: ERCOT + weather data cache

**Type:** AFK (ERCOT keys optional) · **Priority:** P0 · **Blocked by:** 01 · **User stories:** 1, 15, 16, 17

## What to build
An ingest CLI (`make data`) that caches, per dataset per day, the datasets listed in the spec's *Data decisions* for Dec 5, 2025 to the latest day. The settlement points are `LZ_HOUSTON`, `LZ_NORTH`, `LZ_SOUTH`, `HB_HOUSTON`, `HB_NORTH` and `HB_SOUTH`, plus Open-Meteo hourly temperature for Houston, DFW, Austin and San Antonio. Pre-RTC+B history is optional behind a flag.

- **Sources.** Prefer keyless sources: ERCOT's public historical archives through the `gridstatus` OSS library, and Open-Meteo. Verify during implementation which datasets are keyless. Use the ERCOT Public API only when keys exist in `.env`, throttled to its 30 requests per minute.
- **Queryable cache.** DuckDB views unify everything in UTC, with a `regime` column.
- **`data-audit`** reports missing or partial days.
- **`demo-days`** ranks days by max RT price and by intraday spread at a chosen settlement point.
- **Data tab.** A day picker and an RT vs DAM price chart for the picked day.
- **DATA.md** documents every dataset: report ID, source, coverage and quirks. Quirks include the RTC+B regime break, ORDC history only, forecasts that report HSL rather than output, and forecast vintages.

Tracer bullet first: get **one** dataset (RT SPP) for **one** day into the cache and onto the Data tab. Then widen.

## Demo path
`make data` → `demo-days` prints the top 10 spike days → pick one in the Data tab → RT vs DAM chart.

## Acceptance criteria
- [ ] Re-running `make data` fetches only missing days (idempotent, resumable).
- [ ] Credential-gated datasets are fetched when keys exist in `.env`. Otherwise `data-audit` lists them as `pending-credentials`, the ticket still completes, and the issue gets the label `needs-keys` plus a one-line comment saying what the keys would unlock.
- [ ] The throttle never exceeds the configured request rate (unit test with a fake client and clock).
- [ ] Timestamps are UTC, and 2026-03-08 has 92 fifteen-minute intervals (test).
- [ ] `data-audit` lists gaps explicitly; nothing is silently skipped.
- [ ] `demo-days` output is computed from the cache, with a test on the fixture.
- [ ] DATA.md exists and covers every cached dataset.
- [ ] No API key or cached data file is committed.

## Optional human step
Register for the ERCOT Public API (US IP) and paste the keys into `.env`, then re-run `make data` to backfill the gated datasets.

## Out of scope
Using the data in replay (ticket 04) or modelling (tickets 10 and 11).
