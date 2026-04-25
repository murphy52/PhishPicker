"""Nightly smoke-test harness for ongoing model validation.

Each morning we fetch yesterday's Phish setlist from phish.net, replay it
slot-by-slot against the deployed scorer, and log the predicted top-K plus
the rank of the actual song that was played. The resulting JSONL file is a
ground-truth audit log: does our LambdaRank actually pick what Phish plays?

Design notes
------------
* We do NOT apply post-rules (``apply_post_rules``) during replay. The smoke
  test wants the raw model signal, including songs the scorer "should" have
  downweighted but didn't — that surfaces whether the no-repeat rule is load-
  bearing vs incidental.
* One JSONL record per show (not per slot). Slots roll up into ``record.slots``.
* Idempotent: a second run on the same date is a no-op unless ``overwrite=True``.
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from phishpicker.model.scorer import Scorer
from phishpicker.phishnet.client import PhishNetClient

log = logging.getLogger(__name__)

MODEL_VERSION = "0.2.0-lightgbm"


def _load_existing_records(output_path: Path) -> list[dict]:
    """Load all JSONL records from ``output_path``. Blank/invalid lines skipped."""
    if not output_path.exists():
        return []
    out: list[dict] = []
    for line in output_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # Tolerate hand-edited or partially-written files — skip garbage.
            log.warning("skipping malformed JSONL line in %s", output_path)
    return out


def _write_records(output_path: Path, records: list[dict]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _append_record(output_path: Path, record: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a") as fh:
        fh.write(json.dumps(record))
        fh.write("\n")


def _name_map(conn: sqlite3.Connection, song_ids: list[int]) -> dict[int, str]:
    if not song_ids:
        return {}
    placeholders = ",".join("?" * len(song_ids))
    rows = conn.execute(
        f"SELECT song_id, name FROM songs WHERE song_id IN ({placeholders})",
        song_ids,
    ).fetchall()
    return {r["song_id"]: r["name"] for r in rows}


def _summarize(record: dict) -> str:
    slots = record["slots"]
    ranks = [s["actual_rank"] for s in slots if s["actual_rank"] is not None]
    if not ranks:
        return (
            f"smoke {record['date']} {record['venue']}: {record['total_slots']} slots, "
            "no ranks computed."
        )
    ranks_sorted = sorted(ranks)
    median = ranks_sorted[len(ranks_sorted) // 2]
    top1 = sum(1 for r in ranks if r == 1)
    top5 = sum(1 for r in ranks if r <= 5)
    return (
        f"smoke {record['date']} {record['venue']}: {len(ranks)} slots, "
        f"median rank {median}, Top-1 {top1}/{len(ranks)}, Top-5 {top5}/{len(ranks)}."
    )


def run_nightly_smoke(
    conn: sqlite3.Connection,
    client: PhishNetClient,
    scorer: Scorer,
    date: str,
    output_path: Path,
    top_k: int = 10,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Replay ``date``'s Phish setlist against ``scorer`` and write a JSONL record.

    Returns a dict with ``status`` in {"ok", "no-setlist", "skipped"}. On "ok",
    the dict also carries ``record`` (the written dict) and ``summary`` (a one-
    line human-readable string suitable for stdout).
    """
    # 1. Fetch setlist. Date-based endpoint returns all rows for that show.
    raw = client._get(f"setlists/showdate/{date}.json", {})
    rows = [r for r in raw if r.get("artist_name") == "Phish"]
    if not rows:
        log.info("no setlist yet for %s", date)
        return {"status": "no-setlist", "date": date}

    # 2. Idempotency guard. Inspect existing output for the same show_id.
    show_id = int(rows[0]["showid"])
    existing = _load_existing_records(output_path)
    if any(r.get("show_id") == show_id for r in existing):
        if not overwrite:
            log.info("show %s already recorded; pass overwrite=True to redo", show_id)
            return {"status": "skipped", "date": date, "show_id": show_id}
        # Drop the old row; we'll append the fresh one below.
        existing = [r for r in existing if r.get("show_id") != show_id]
        _write_records(output_path, existing) if existing else output_path.write_text("")

    # 3. Sort slots in playback order. phish.net's 'E' for encore must sort last.
    def _slot_sort_key(row: dict) -> tuple[int, int]:
        set_label = str(row["set"]).upper()
        # Map known labels to a stable integer ordering; unknown labels go last.
        order = {"1": 1, "2": 2, "3": 3, "4": 4, "E": 5, "E2": 6, "E3": 7}
        return (order.get(set_label, 99), int(row["position"]))

    rows.sort(key=_slot_sort_key)

    # 4. Candidate pool: every song in the DB. That's the realistic "what could
    # the model have picked" space and what training uses at eval time too.
    song_id_rows = conn.execute("SELECT song_id FROM songs").fetchall()
    candidate_ids = [r["song_id"] for r in song_id_rows]
    if not candidate_ids:
        log.warning("no songs in DB — cannot score")
        return {"status": "no-setlist", "date": date, "reason": "empty-songs-table"}

    venue_name = rows[0].get("venue") or ""
    venue_id_raw = rows[0].get("venueid")
    venue_id: int | None = int(venue_id_raw) if venue_id_raw is not None else None

    # 5. Per-slot replay.
    played_songs: list[int] = []
    prev_trans_mark = ","
    prev_set_number: str | None = None
    slots_into_current_set = 1
    slot_records: list[dict] = []

    for idx, row in enumerate(rows, start=1):
        set_number = str(row["set"]).upper()
        actual_song_id = int(row["songid"])
        actual_song_name = row.get("song") or f"#{actual_song_id}"

        if prev_set_number is not None and prev_set_number != set_number:
            slots_into_current_set = 1

        scored = scorer.score_candidates(
            conn=conn,
            show_date=date,
            venue_id=venue_id,
            played_songs=list(played_songs),
            current_set=set_number,
            candidate_song_ids=candidate_ids,
            prev_trans_mark=prev_trans_mark,
            prev_set_number=prev_set_number,
            slots_into_current_set=slots_into_current_set,
        )
        # Sort by score desc; tiebreak on song_id for determinism.
        ranked = sorted(scored, key=lambda pair: (-pair[1], pair[0]))

        # Rank of the actual song (1-indexed). None if it's somehow absent
        # from the candidate pool (shouldn't happen — ingest stubs missing
        # songs — but guard anyway).
        actual_rank: int | None = None
        for pos, (sid, _score) in enumerate(ranked, start=1):
            if sid == actual_song_id:
                actual_rank = pos
                break

        top_ids = [sid for sid, _ in ranked[:top_k]]
        names = _name_map(conn, top_ids)
        top_k_entries = [
            {"song_id": sid, "name": names.get(sid, f"#{sid}"), "rank": pos}
            for pos, sid in enumerate(top_ids, start=1)
        ]

        slot_records.append(
            {
                "slot": idx,
                "set": set_number,
                "position": int(row["position"]),
                "actual_song_id": actual_song_id,
                "actual_song": actual_song_name,
                "actual_rank": actual_rank,
                "top_k": top_k_entries,
            }
        )

        played_songs.append(actual_song_id)
        prev_trans_mark = row.get("trans_mark") or ","
        prev_set_number = set_number
        slots_into_current_set += 1

    record = {
        "date": date,
        "show_id": show_id,
        "venue": venue_name,
        "scorer_name": getattr(scorer, "name", "unknown"),
        "model_version": MODEL_VERSION,
        "total_slots": len(slot_records),
        "slots": slot_records,
    }
    _append_record(output_path, record)
    summary = _summarize(record)
    log.info(summary)
    return {"status": "ok", "record": record, "summary": summary}
