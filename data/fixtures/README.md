# Fixtures

`rtm_spp_lz_houston_2025-12-10.csv` — 96 x 15-minute Market Intervals of RT
Settlement Point Price for `LZ_HOUSTON`, dated after the Dec 5, 2025 RTC+B
go-live. See `docs/DECISIONS.md` ADR-007: this is a deterministic placeholder
shaped like ERCOT's real `NP6-905-CD` export (same columns, interval count and
a realistic evening scarcity price shape), checked in because the ERCOT API
subscription key is optional and wasn't available to generate a live pull.
Ticket 03 replaces it with the real ingest cache.

Columns: `interval_start_utc` (ISO 8601, UTC), `settlement_point`,
`price_usd_per_mwh`.
