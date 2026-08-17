"""Build a tariff schedule from episode configuration + official source documents.

The schedule is the normalized-layer artefact that the tariff engine consumes.
Product lists are always re-parsed from the source PDFs; only dates, rates and
document identifiers come from configuration, and each of those carries the
verbatim sentence it was read from.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from ..adapters.federal_register import (
    AnnexParse,
    FRDocument,
    annex_to_records,
    fetch_document_metadata,
    fetch_notice_pdf,
    parse_all_annexes,
    parse_annex,
)
from ..paths import CONFIG
from ..tariff.records import Confidence, RecordType, SourceRef, TariffRecord

SCHEMA_VERSION = "tariff_schedule_v1"

SCHEDULE_SCHEMA: dict[str, Any] = {
    "record_id": pl.String,
    "episode_id": pl.String,
    "action_id": pl.String,
    "record_type": pl.String,
    "product_code": pl.String,
    "product_code_level": pl.Int8,
    "product_code_vintage": pl.String,
    "partner_country_code": pl.String,
    "announcement_date": pl.Date,
    "effective_date": pl.Date,
    "expiry_date": pl.Date,
    "ad_valorem_rate": pl.Float64,
    "confidence": pl.String,
    "partial_line": pl.Boolean,
    "partial_line_note": pl.String,
    "partial_line_excluded_codes": pl.String,
    "notes": pl.String,
    "tags": pl.String,
    "source_document_id": pl.String,
    "source_citation": pl.String,
    "source_title": pl.String,
    "source_url": pl.String,
    "source_publication_date": pl.String,
    "source_checksum_sha256": pl.String,
    "source_locator": pl.String,
}


def load_episode(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = CONFIG / "episodes" / p
    doc: dict[str, Any] = yaml.safe_load(p.read_bytes())
    return doc


def _iso(d: str) -> date:
    return datetime.strptime(str(d), "%Y-%m-%d").date()


def build_records_from_episode(
    episode: dict[str, Any],
    *,
    offline_pdf_dir: Path | None = None,
    verbose: bool = True,
) -> tuple[list[TariffRecord], list[AnnexParse]]:
    """Parse every action in an episode into tariff records.

    ``offline_pdf_dir`` lets tests and air-gapped runs supply pre-downloaded
    ``<document_number>.pdf`` files instead of hitting the network.
    """
    episode_id = episode["episode_id"]
    vintage = episode.get("product_code_vintage", "UNKNOWN")
    country = str(episode.get("partner_country_code", "5700"))

    records: list[TariffRecord] = []
    parses: list[AnnexParse] = []
    lines_by_action: dict[str, AnnexParse] = {}

    for action in episode.get("actions", []):
        doc_num = action["federal_register_document"]
        action_id = action["action_id"]
        parse_cfg = action.get("parse", {})
        method = parse_cfg.get("method", "operative_anchor_hts8")
        rtype = RecordType[action.get("record_type", "ADDITIONAL_DUTY")]

        if offline_pdf_dir is not None:
            pdf_path = Path(offline_pdf_dir) / f"{doc_num}.pdf"
            doc = FRDocument(
                document_number=doc_num,
                citation=action.get("citation", ""),
                title=action.get("label", ""),
                publication_date=str(action.get("publication_date", "")),
                html_url=f"https://www.federalregister.gov/d/{doc_num}",
                pdf_url="",
            )
            from ..provenance import sha256_file

            checksum = sha256_file(pdf_path) if pdf_path.exists() else "OFFLINE_NO_FILE"
        else:
            doc = fetch_document_metadata(doc_num)
            fetched = fetch_notice_pdf(doc)
            pdf_path, checksum = fetched.path, fetched.sha256

        if method == "operative_anchor_hts8_multi":
            # This notice imposes more than one action. Select the annex by the
            # Chapter 99 heading named in the config, so the action id is still
            # tied to the operative text rather than to a page range.
            want = action["chapter99_heading"]
            doc_parse = parse_all_annexes(pdf_path, doc_num)
            selected = doc_parse.by_heading(want)
            if selected is None:
                raise ValueError(
                    f"{action_id}: heading {want} not found in {doc_num}; "
                    f"found {[a.chapter99_heading for a in doc_parse.annexes]}"
                )
            annex = selected
            parses.append(annex)
            lines_by_action[f"{action_id}:{doc_num}"] = annex
            if verbose:
                print(
                    f"  {action_id} <- {doc_num} {action.get('citation','')}: "
                    f"{annex.parsed_line_count} lines under {want} "
                    f"({len(annex.hts8_codes)} full + {len(annex.partial_lines)} partial) "
                    f"[of {len(doc_parse.annexes)} actions in this notice; "
                    f"document total {doc_parse.parsed_total} vs stated "
                    f"{doc_parse.stated_total}]"
                )
                for w in annex.warnings:
                    print(f"      ! {w}")
        elif method == "operative_anchor_hts8":
            annex = parse_annex(pdf_path, doc_num)
            parses.append(annex)
            lines_by_action[f"{action_id}:{doc_num}"] = annex
            if verbose:
                flag = (
                    "OK"
                    if annex.count_matches_notice
                    else ("UNVERIFIED" if annex.count_matches_notice is None else "MISMATCH")
                )
                print(
                    f"  {action_id} <- {doc_num} {action.get('citation','')}: "
                    f"{annex.parsed_line_count} HTS8 lines "
                    f"(notice states {annex.stated_line_count}) [{flag}]"
                )
                for w in annex.warnings:
                    print(f"      ! {w}")
        elif method == "inherit_lines_from":
            src_key = (
                f"{parse_cfg['inherit_from_action']}:{parse_cfg['inherit_from_document']}"
            )
            if src_key not in lines_by_action:
                raise ValueError(
                    f"{action_id}: cannot inherit lines from {src_key}; the source action must "
                    "be parsed earlier in the episode file"
                )
            base = lines_by_action[src_key]
            annex = AnnexParse(
                document_number=doc_num,
                chapter99_heading=action.get("chapter99_heading", base.chapter99_heading),
                hts8_codes=list(base.hts8_codes),
                anchor_page=-1,
                last_page=-1,
                stated_line_count=base.stated_line_count,
                parsed_line_count=base.parsed_line_count,
                count_matches_notice=base.count_matches_notice,
                partial_lines={k: list(v) for k, v in base.partial_lines.items()},
                warnings=[
                    f"lines inherited from {src_key}; this notice amends the rate for the "
                    "already-covered lines and does not restate them"
                ],
            )
            parses.append(annex)
            if verbose:
                print(
                    f"  {action_id} <- {doc_num} {action.get('citation','')}: "
                    f"RATE_CHANGE to {action['ad_valorem_rate']:.0%} on "
                    f"{action['effective_date']} over {annex.parsed_line_count} inherited lines"
                )
        else:
            raise ValueError(f"unknown parse method {method!r} for action {action_id}")

        records.extend(
            annex_to_records(
                annex,
                doc,
                episode_id=episode_id,
                action_id=action_id,
                effective_date=_iso(action["effective_date"]),
                announcement_date=_iso(action["announcement_date"]),
                ad_valorem_rate=float(action["ad_valorem_rate"]),
                product_code_vintage=vintage,
                checksum=checksum,
                partner_country_code=country,
                record_type=rtype,
            )
        )

    return records, parses


def records_to_frame(records: list[TariffRecord]) -> pl.DataFrame:
    rows = []
    for r in records:
        rows.append(
            {
                "record_id": r.record_id,
                "episode_id": r.episode_id,
                "action_id": r.action_id,
                "record_type": r.record_type.value,
                "product_code": r.product_code,
                "product_code_level": r.product_code_level,
                "product_code_vintage": r.product_code_vintage,
                "partner_country_code": r.partner_country_code,
                "announcement_date": r.announcement_date,
                "effective_date": r.effective_date,
                "expiry_date": r.expiry_date,
                "ad_valorem_rate": r.ad_valorem_rate,
                "confidence": r.confidence.value,
                "partial_line": r.partial_line,
                "partial_line_note": r.partial_line_note,
                "partial_line_excluded_codes": "|".join(r.partial_line_excluded_codes),
                "notes": r.notes,
                "tags": "|".join(r.tags),
                "source_document_id": r.source.document_id,
                "source_citation": r.source.citation,
                "source_title": r.source.title,
                "source_url": r.source.url,
                "source_publication_date": r.source.publication_date,
                "source_checksum_sha256": r.source.checksum_sha256,
                "source_locator": r.source.page_or_locator,
            }
        )
    return pl.DataFrame(rows, schema=SCHEDULE_SCHEMA)


def frame_to_records(df: pl.DataFrame) -> list[TariffRecord]:
    out: list[TariffRecord] = []
    for row in df.iter_rows(named=True):
        src = SourceRef(
            document_id=row["source_document_id"],
            citation=row["source_citation"],
            title=row["source_title"],
            url=row["source_url"],
            publication_date=row["source_publication_date"],
            checksum_sha256=row["source_checksum_sha256"],
            page_or_locator=row["source_locator"] or "",
        )
        out.append(
            TariffRecord(
                record_id=row["record_id"],
                episode_id=row["episode_id"],
                action_id=row["action_id"],
                record_type=RecordType(row["record_type"]),
                product_code=row["product_code"],
                product_code_level=int(row["product_code_level"]),
                product_code_vintage=row["product_code_vintage"],
                partner_country_code=row["partner_country_code"],
                announcement_date=row["announcement_date"],
                effective_date=row["effective_date"],
                expiry_date=row["expiry_date"],
                ad_valorem_rate=row["ad_valorem_rate"],
                source=src,
                confidence=Confidence(row["confidence"]),
                partial_line=bool(row["partial_line"]),
                partial_line_note=row["partial_line_note"] or "",
                partial_line_excluded_codes=tuple(
                    c for c in (row.get("partial_line_excluded_codes") or "").split("|") if c
                ),
                notes=row["notes"] or "",
                tags=tuple(t for t in (row["tags"] or "").split("|") if t),
            )
        )
    return out


def parse_summary(parses: list[AnnexParse]) -> list[dict[str, Any]]:
    return [asdict(p) | {"hts8_codes": len(p.hts8_codes)} for p in parses]
