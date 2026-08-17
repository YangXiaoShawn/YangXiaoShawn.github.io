# Product Exclusions and the Intention-to-Treat Gap

> **DATA PROVENANCE: OFFICIAL SOURCES**
>
> All figures below derive from official statistical or legal sources.
>
> run_id `20260811T201708Z-b1495fb3` · git `3c51a06-dirty` · config `sample_slice.yaml` (sha256 `b1495fb3b363`) · data period 2017-01 to 2020-02 · generated 2026-08-11T20:17:08.149704+00:00


USTR granted product exclusions from the Section 301 duties. This document establishes, quantitatively, why those exclusions cannot be incorporated into the treatment variable, and bounds the resulting gap.

## Why exclusion adjustment cannot be done from published trade data

Across 11 USTR exclusion notices covering this sample window, **16 exclusions are expressed as a 10-digit subheading and 824 as a specially prepared product description** — only 1.9% could ever be mapped to trade data.

A product description identifies a subset of a statistical reporting number by physical characteristics. U.S. import statistics are published at that number and no finer, so the share of a line's imports that was excluded is not observable. This is a property of the data, not a parsing problem that more effort would solve.

Two further obstacles are recorded so they do not look like open tasks: every annex is an embedded raster image with no text layer, and OCR is not used here because it would introduce an unvalidatable transcription channel into a legal treatment variable; and the USITC HTS exposes the exclusion headings but not the enumerated product lists in their U.S. notes.

**notices**

| document_number | publication_date | n_ten_digit_exclusions | n_prose_exclusions | retroactive_to | expires | annex_is_image_only |
| --- | --- | --- | --- | --- | --- | --- |
| 2018-28277 | 2018-12-28 | 7 | 24 | 2018-07-06 | 2019-12-28 | yes |
| 2019-05588 | 2019-03-25 | 3 | 30 | 2018-07-06 | 2020-03-25 | yes |
| 2019-07758 | 2019-04-18 | 0 | 21 | 2018-07-06 | 2020-04-18 | yes |
| 2019-09872 | 2019-05-14 | 5 | 35 | 2018-07-06 | 2020-05-14 | yes |
| 2019-11573 | 2019-06-04 | 1 | 88 | 2018-07-06 | 2020-06-04 | yes |
| 2019-14562 | 2019-07-09 | 0 | 110 | 2018-07-06 | 2020-07-09 | yes |
| 2019-16256 | 2019-07-31 | 0 | 69 | 2018-08-23 | 2020-07-31 | yes |
| 2019-16886 | 2019-08-07 | 0 | 10 | 2018-09-24 | 2020-08-07 | yes |
| 2019-20440 | 2019-09-20 | 0 | 89 | 2018-08-23 | 2020-09-20 | yes |
| 2019-20441 | 2019-09-20 | 0 | 310 | 2018-07-06 | 2020-09-20 | yes |
| 2019-20442 | 2019-09-20 | 0 | 38 | 2018-09-24 | 2020-09-20 | yes |


## Exclusions are retroactive, which is a third kind of date

Exclusions apply from the **effective date of the underlying action**, not from publication, and expire one year after publication. The first notice was published 2018-12-28 and applies retroactively to 2018-07-06. Announcement, publication and effective dates are three separate facts and are stored separately throughout this project.

## Empirical bound on the intention-to-treat gap

Share of treated customs value where the duty Customs actually calculated falls more than 3 percentage points short of the statutory rate:

- before exclusions were first granted (2018-12-01): **10.9%**
- after: **20.0%**

The pre-exclusion figure cannot be caused by exclusions; it reflects preference programmes, Chapter 98 provisions and duty-free entry. Only the increase is attributable to exclusions, and even that is an **upper** bound, since those other channels also grew. The estimates in this project are intention-to-treat with respect to the statutory list, and this is how far that can be from treatment-on-the-treated.

**by month**

| month_date | n_obs | share_obs_short | share_value_short | median_gap |
| --- | --- | --- | --- | --- |
| 2018-07-01 | 957 | 0.3062 | 0.3532 | -0.0389 |
| 2018-08-01 | 1199 | 0.2185 | 0.3606 | 0.0000 |
| 2018-09-01 | 2062 | 0.0897 | 0.0559 | 0.0017 |
| 2018-10-01 | 2964 | 0.1107 | 0.0891 | 0.0000 |
| 2018-11-01 | 2965 | 0.0921 | 0.0785 | 0.0000 |
| 2018-12-01 | 2974 | 0.0955 | 0.0932 | 0.0000 |
| 2019-01-01 | 2936 | 0.1100 | 0.1238 | 0.0000 |
| 2019-02-01 | 2858 | 0.1141 | 0.1169 | 0.0000 |
| 2019-03-01 | 2858 | 0.1130 | 0.1169 | 0.0000 |
| 2019-04-01 | 2895 | 0.1102 | 0.1150 | 0.0000 |
| 2019-05-01 | 2953 | 0.5842 | 0.7137 | 0.0846 |
| 2019-06-01 | 2905 | 0.3174 | 0.4112 | 0.0128 |
| 2019-07-01 | 2948 | 0.1577 | 0.1928 | 0.0000 |
| 2019-08-01 | 2948 | 0.1452 | 0.1962 | 0.0000 |
| 2019-09-01 | 3379 | 0.1563 | 0.1690 | 0.0000 |
| 2019-10-01 | 3398 | 0.1460 | 0.1459 | 0.0000 |
| 2019-11-01 | 3343 | 0.1472 | 0.1288 | 0.0000 |
| 2019-12-01 | 3381 | 0.1429 | 0.1403 | 0.0000 |
| 2020-01-01 | 3405 | 0.1747 | 0.1912 | 0.0000 |
| 2020-02-01 | 3297 | 0.1762 | 0.2119 | 0.0000 |


---

## Reproducibility

- run id: `20260811T201708Z-b1495fb3`
- git commit: `3c51a06-dirty`
- configuration: `sample_slice.yaml` (sha256 `b1495fb3b363c158ae3b162babd17a515adfc9a8c26038b6c09edb9ec55652a3`)
- data provenance: `OFFICIAL`
- data period: 2017-01 to 2020-02
- generated: 2026-08-11T20:17:08.149704+00:00
- python 3.12.13 on macOS-26.6.1-arm64-arm-64bit

_This document is generated by `scripts/generate_reports.py`. Do not edit it by hand; edit the generator or the underlying result tables._
