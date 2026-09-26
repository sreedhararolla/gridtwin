# Data

The ingest cache is DuckDB + Parquet under `data/cache/` (never committed —
see `.gitignore`). One Parquet file per dataset, per key, per day:
`data/cache/<dataset>/<key>/<YYYY-MM-DD>.parquet`. Every row carries a
`regime` column (`post_rtcb` from 2025-12-05 onward, else `pre_rtcb`) and a
`source` column (`ercot_live`, `ercot_historical`, `open_meteo` or
`fixture_seed`).

Run `make data` to populate it: `... ingest` (add `--datasets rt_spp` to
limit it) then `... backfill-rt-spp`. Use `... audit` to see gaps,
`... demo-days` to rank cached days, and `... seed-fixture-day` to seed one
demo day from the checked-in fixture (tests/offline only; see ADR-008 below).

**RT SPP backfill.** ERCOT's MIS keeps only the last ~9 days of the daily
`NP6-905-CD` documents, so the daily fetch reports `No objects to
concatenate` for anything older. `backfill-rt-spp` fills every missing day
from ERCOT's yearly **`NP6-785-ER`** "Historical RTM Load Zone and Hub
Prices" workbook (keyless; tagged `source=ercot_historical`). That workbook
lists each load zone twice; we keep type `LZ` (the settlement price) and
drop `LZEW` (energy-weighted). Hours are hour-ending Central time; the
repeated fall-back hour is disambiguated by `Repeated Hour Flag`, so
Mar 8, 2026 has 92 intervals. gridstatus's own `get_rtm_spp(year)` crashes
on current pandas, so `marketdata/rtm_history.py` parses the workbook
itself. Days already cached from the daily fetch are kept as-is.

**DAM SPP backfill.** Same story for the day-ahead market: `backfill-dam-spp`
(also in `make data`) fills missing `dam_spp` days from the yearly **`NP4-180-ER`**
"Historical DAM Load Zone and Hub Prices" workbook (hourly, hour-ending Central, same
`Repeated Hour Flag` handling; tagged `source=ercot_historical`). As of ticket 09 the
cache holds DAM SPP for 2025-12-05 → 2026-09-25. The LP planner's price forecast reads
it (`marketdata/forecast.py`, ADR-014).

**Weather for the risk model.** Ticket 10 ingested `weather_temperature` for all four
cities over 2025-12-05 → 2026-09-25 (`... ingest --datasets weather_temperature --start
2025-12-05 --end 2026-09-25`). The scarcity-risk model reads `houston`
(`RISK_WEATHER_CITY`). These are archive *observations*, so the model only uses the last
observed hour at decision time, never the target hour's temperature (MODEL.md).
Load/wind/solar forecasts and outages are still not cached, so the model runs without
them (ticket 10's cut line); see MODEL.md.

As of ticket 04 the cache holds real RT SPP for 2025-12-05 → 2026-09-25
(`demo-days` #1 at `LZ_HOUSTON`: **2026-01-28**, max $1,284.81/MWh).

## Datasets

| Dataset | Report ID | Source | Key | Coverage | Quirks |
|---|---|---|---|---|---|
| `rt_spp` | `NP6-905-CD` | `gridstatus.Ercot.get_spp` (keyless) | `ALL` (all 6 settlement points in one file) | 2025-12-05 → latest, post-RTC+B; pre-RTC+B optional behind `--include-pre-rtcb` | RTC+B (Dec 5, 2025) changed how RT SPP is calculated; never compare regimes without the flag. |
| `dam_spp` | `NP4-190-CD` | `gridstatus.Ercot.get_spp` (keyless) | `ALL` | same window | DAM is hourly, published the day before; joins to RT need care with the interval grain. |
| `as_prices_dam` | `NP4-188-CD` | `gridstatus.Ercot.get_as_prices` (keyless) | `ALL` | same window | Context only, per spec — never used for dispatch or bidding. RT AS clearing (`NP6-331-CD`) is not separately cached; gridstatus does not expose it as a distinct keyless call, and it may be missing from the API per spec. |
| `load_forecast` | `NP3-565-CD` | `gridstatus.Ercot.get_load_forecast` (keyless) | `ALL` | 7-day forecast, fetched daily | **Latest vintage only.** The keyless MIS archive overwrites earlier forecast runs; only the most recently published forecast for each future interval is cached. Using this to backtest the risk model (ticket 10) carries a look-ahead leakage risk versus what was actually known at decision time. `load_forecast_vintages` (below) is the fix. |
| `load_forecast_vintages` | `NP3-565-CD` (all vintages) | Keyed ERCOT Public API (`ercot_public_api.py`) | `ALL` | only when `ERCOT_API_USERNAME`/`PASSWORD`/`SUBSCRIPTION_KEY` are set in `.env` | Credential-gated by design — the keyless archive can't give us forecast history, only the keyed API republishes every vintage. `data-audit` reports this `pending-credentials` without keys; see the "Optional human step" in ticket 03's issue. |
| `load_actual` | (ERCOT actual system load by weather zone) | `gridstatus.Ercot.get_load_by_weather_zone` (keyless) | `ALL` | same window | — |
| `wind` | `NP4-732-CD` / `NP4-742-CD` | `gridstatus.Ercot.get_wind_actual_and_forecast_hourly` (keyless) | `ALL` | same window | Forecast columns report **HSL (High Sustainable Limit)**, not realized output — don't treat forecast as a delivered-MW prediction. |
| `solar` | `NP4-745-CD` / `NP4-737-CD` | `gridstatus.Ercot.get_solar_actual_and_forecast_hourly` (keyless) | `ALL` | same window | Same HSL-vs-output caveat as wind. |
| `outages` | `NP3-233-CD` | `gridstatus.Ercot.get_hourly_resource_outage_capacity` (keyless) | `ALL` | same window | **ORDC-relevant history only** — the report reflects outages as ERCOT's Operating Reserve Demand Curve pricing uses them, not a full unit-level outage log. |
| `weather_temperature` | Open-Meteo hourly archive | `weather_source.fetch_temperature` (keyless, no key) | `houston`, `dfw`, `austin`, `san_antonio` | 2025-12-05 → latest (or `--include-pre-rtcb`) | Only hourly temperature is cached; Open-Meteo's other variables (wind, irradiance) are out of scope for this build. |

## ADR-008: ERCOT is unreachable from the ticket-03 build sandbox

**Amended in ticket 04:** the block was the build machine's VPN egressing
in Japan, not ERCOT. From a US egress (`curl -s https://ipinfo.io/country`
prints `US`) the keyless fetches work, and the cache now holds real days.
If an ingest returns 403 again, check that probe first.

See `docs/DECISIONS.md` ADR-008 for the full account. In short: every
ERCOT-owned host (`www.ercot.com`, `mis.ercot.com`, `api.ercot.com`,
`apiexplorer.ercot.com`) returned `403` from an Incapsula WAF or a TLS
handshake failure when this ticket was built, for both the keyless MIS
archives and the keyed Public API — a network-level block on the build
machine, not a missing-credentials situation. Every fetcher above is
implemented and unit-tested with fakes; `make data` run from a machine that
*can* reach ERCOT (a real dev box, or CI with a US egress IP) will populate
these datasets for real, with no code changes. Open-Meteo weather is
unaffected and was fetched for real in this build. Run `data-audit` to see
exactly which days are missing and why — nothing is silently skipped.

The Data tab and `demo-days` are demoable today via
`uv run python -m gridtwin.marketdata.cli seed-fixture-day`, which loads the
ADR-007 placeholder day into the `rt_spp` cache tagged `source=fixture_seed`
so it's never mistaken for a live ERCOT pull.
