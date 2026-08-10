# Committed public-data fixture

`chicago_tnp_2022-01-01_300.csv` is an authentic 300-row extract from the City of
Chicago's **Transportation Network Providers – Trips (2018–2022)** dataset.
No trip values are simulated. The API's CSV bytes are concatenated without changing
field values; one common header is retained.

## Provenance

- Publisher: City of Chicago
- Socrata dataset ID: `m6dm-c72p`
- Official dataset page: <https://data.cityofchicago.org/Transportation/Transportation-Network-Providers-Trips-2018-2022-/m6dm-c72p>
- API resource: <https://data.cityofchicago.org/resource/m6dm-c72p.csv>
- Retrieved: 2026-08-07
- Rows: 300 plus one header row
- Bytes: 70,621
- SHA-256: `84177e5a72548cc4346df99f0a6b671adb50d7762e23abe041f01b2958b85ad7`

The extract takes the first 25 records in lexical `trip_id` order at each of 12
reported timestamps on 2022-01-01: 00:00, 02:00, ..., 22:00 Chicago local time.
Each request uses this Socrata query shape:

```text
$select=trip_id,trip_start_timestamp,trip_end_timestamp,trip_seconds,trip_miles,
pickup_census_tract,dropoff_census_tract,pickup_community_area,
dropoff_community_area,fare,tip,additional_charges,trip_total,
shared_trip_authorized,trips_pooled,pickup_centroid_latitude,
pickup_centroid_longitude,dropoff_centroid_latitude,dropoff_centroid_longitude
$where=trip_start_timestamp = '2022-01-01T{HH}:00:00'
$order=trip_id
$limit=25
```

The exact URL construction and concatenation are implemented by
`chicago_sample_urls()` and `download_sample(..., refresh=True)` in
`src/casuallab/data.py`. Normal sample runs use this committed file without network
access. A refresh is explicit because the upstream publisher can revise public data;
the checksum makes any revision visible rather than silently replacing the fixture.

## Measurement and use limitations

Per the publisher, trip timestamps are rounded to the nearest 15 minutes, fares to
the nearest $2.50, and tips to the nearest $1.00. Some census tracts are suppressed,
and geographic blanks can also mean a trip endpoint was outside Chicago. The cleaned
schema preserves these facts as measurement and missing-or-suppressed flags.

This is a deterministic engineering fixture, not a probability sample. Its 12 time
strata help exercise a nondegenerate zone-time panel, but it is not representative of
Chicago travel, cannot identify a price elasticity, and cannot support causal claims.

To verify the immutable fixture locally:

```bash
shasum -a 256 data/fixtures/chicago_tnp_2022-01-01_300.csv
```
