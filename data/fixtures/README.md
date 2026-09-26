# Fixtures

`rtm_spp_lz_houston_2025-12-10.csv` — 96 x 15-minute Market Intervals of RT
Settlement Point Price for `LZ_HOUSTON`, dated after the Dec 5, 2025 RTC+B
go-live. See `docs/DECISIONS.md` ADR-007: this is a deterministic placeholder
shaped like ERCOT's real `NP6-905-CD` export (same columns, interval count and
a realistic evening scarcity price shape), checked in because the ERCOT API
subscription key is optional and wasn't available to generate a live pull.
Ticket 03 replaces it with the real ingest cache.

`rtm_spp_lz_houston_2026-01-28.csv`: the real #1 `demo-days` spike day at
`LZ_HOUSTON` (max $1,284.81/MWh). It holds 96 intervals exported from the ingest cache
(ERCOT `NP6-785-ER`, `source=ercot_historical`). The Seam A spike-day Scenario Report
runs on it in CI, so no cache is needed.

Columns: `interval_start_utc` (ISO 8601, UTC), `settlement_point`,
`price_usd_per_mwh`.
