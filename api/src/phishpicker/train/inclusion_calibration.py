"""Calibration backtest for the show-level 'Likely Tonight' inclusion model.

The question: when Likely Tonight says a song has an 8% chance of being
played anywhere tonight, is it played about 8% of the time? That decides
whether a "bonus pick" (one song per show, scored if played anywhere, points
by likelihood band) can be priced on these chances.

Method (honestly nested, nothing sees the night it scores):
- Walk forward in blocks of shows: retrain on every show dated before the
  block, predict the block. Features use only plays strictly before each
  show (see `inclusion_features`).
- Apply the run rule (songs already played earlier in the run are capped).
- Calibrate each block with an isotonic map fitted only on the walk-forward
  chances of the shows in the `calibration_days` before that block — the
  same recipe `train_inclusion` uses for the shipped calibration.
Then compare raw, run-rule and run-rule+calibrated chances with what was
played, by bonus band (current 5-band and proposed 4-band schemes) and in
finer reliability bins, over the whole test period and a recent slice; plus
a trailing 12-month play-rate baseline and an out-of-sample check of a
saved production artifact.
"""

from __future__ import annotations

import bisect
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from phishpicker.db.connection import open_db
from phishpicker.inclusion import (
    RUN_REPEAT_CHANCE,
    InclusionCalibration,
    apply_run_rule,
    file_sha256,
)
from phishpicker.model.lightgbm_scorer import LightGBMScorer
from phishpicker.train.inclusion_features import (
    INCLUSION_FEATURE_COLUMNS,
    UNIVERSE_YEARS,
    InclusionHistory,
    InclusionRows,
    build_inclusion_rows,
    played_earlier_in_run,
)
from phishpicker.train.inclusion_runner import (
    _PARAMS,
    DEFAULT_BLOCK_SHOWS,
    DEFAULT_CALIBRATION_DAYS,
    fit_isotonic,
    walk_forward,
)


@dataclass(frozen=True)
class Band:
    name: str
    lo: float  # inclusive lower edge
    points: int  # bonus points for a correct pick in this band


# The first proposal: five bands, most likely first.
BANDS: tuple[Band, ...] = (
    Band("Safe bet", 0.35, 5),
    Band("Good bet", 0.15, 10),
    Band("Long shot", 0.05, 20),
    Band("Deep cut", 0.01, 40),
    Band("Wild card", 0.0, 75),
)
POINT_LEVELS: tuple[int, ...] = tuple(b.points for b in BANDS)

# The revised proposal: Safe bet merged into Good bet, long tail paid more.
PROPOSED_BANDS: tuple[Band, ...] = (
    Band("Good bet", 0.15, 10),
    Band("Long shot", 0.05, 25),
    Band("Deep cut", 0.01, 60),
    Band("Wild card", 0.0, 150),
)

# Finer bins for the reliability table and ECE. Most predictions sit under
# 10%, so the low end is cut finely.
RELIABILITY_EDGES: tuple[float, ...] = (
    0.0,
    0.005,
    0.01,
    0.02,
    0.03,
    0.05,
    0.075,
    0.10,
    0.15,
    0.20,
    0.25,
    0.35,
    0.50,
    0.65,
    0.80,
    1.0,
)

# Log loss clips predictions to [eps, 1-eps]: the raw frequency baseline says
# 0% for songs unplayed in the last year, and one of those getting played
# would otherwise cost infinity.
LOG_LOSS_EPS = 1e-4

# Default length of the "recent" slice.
RECENT_DAYS = 182


# --------------------------------------------------------------- pure parts


def assign_bands(probs, bands: tuple[Band, ...] = BANDS) -> np.ndarray:
    """Index into `bands` for each probability (lower edges inclusive)."""
    p = np.asarray(probs, dtype=float)
    upper_los = np.array([b.lo for b in bands[:-1]])
    return np.sum(p[:, None] < upper_los[None, :], axis=1).astype(int)


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials (95% by default)."""
    if n == 0:
        return 0.0, 1.0
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def expected_points(rate: float, points: tuple[int, ...] = POINT_LEVELS) -> dict[int, float]:
    """Expected bonus points per pick: hit rate x points, at each point level."""
    return {pts: rate * pts for pts in points}


def brier_score(probs, y) -> float:
    p, yy = np.asarray(probs, dtype=float), np.asarray(y, dtype=float)
    return float(np.mean((p - yy) ** 2))


def log_loss(probs, y, eps: float = LOG_LOSS_EPS) -> float:
    p = np.clip(np.asarray(probs, dtype=float), eps, 1 - eps)
    yy = np.asarray(y, dtype=float)
    return float(-np.mean(yy * np.log(p) + (1 - yy) * np.log(1 - p)))


def _bin_index(p: np.ndarray, edges: tuple[float, ...]) -> np.ndarray:
    # edges[i] <= p < edges[i+1]; the top bin also takes p == edges[-1].
    return np.digitize(p, np.asarray(edges[1:-1]), right=False)


def reliability_table(probs, y, edges: tuple[float, ...] = RELIABILITY_EDGES) -> list[dict]:
    p, yy = np.asarray(probs, dtype=float), np.asarray(y, dtype=int)
    idx = _bin_index(p, edges)
    rows = []
    for i in range(len(edges) - 1):
        m = idx == i
        n = int(m.sum())
        k = int(yy[m].sum())
        if n:
            lo, hi = wilson_interval(k, n)
            stats = {
                "mean_pred": float(p[m].mean()),
                "actual_rate": k / n,
                "ci_low": lo,
                "ci_high": hi,
            }
        else:
            stats = {"mean_pred": None, "actual_rate": None, "ci_low": None, "ci_high": None}
        rows.append({"lo": edges[i], "hi": edges[i + 1], "n": n, "n_played": k, **stats})
    return rows


def expected_calibration_error(probs, y, edges: tuple[float, ...] = RELIABILITY_EDGES) -> float:
    """Count-weighted mean |mean predicted - actual rate| over the bins."""
    rows = reliability_table(probs, y, edges)
    total = sum(r["n"] for r in rows)
    if not total:
        return 0.0
    return float(
        sum(r["n"] * abs(r["mean_pred"] - r["actual_rate"]) for r in rows if r["n"]) / total
    )


def band_table(probs, y, show_ids, bands: tuple[Band, ...] = BANDS, tiebreak=None) -> list[dict]:
    """Per bonus band: volume, mean predicted, actual rate (Wilson 95%), songs
    per show, expected points, and how each show's top song in the band did
    (what a player picking the band's best song gets). Songs tied at the top
    are split by `tiebreak` (the served list's order), then count as a coin
    flip among whatever is still tied."""
    p = np.asarray(probs, dtype=float)
    yy = np.asarray(y, dtype=int)
    shows = np.asarray(show_ids)
    tb = None if tiebreak is None else np.asarray(tiebreak, dtype=float)
    n_shows = len(np.unique(shows))
    idx = assign_bands(p, bands)
    points = tuple(b.points for b in bands)
    out = []
    for bi, band in enumerate(bands):
        m = idx == bi
        n = int(m.sum())
        k = int(yy[m].sum())
        row = {
            "band": band.name,
            "lo": band.lo,
            "hi": bands[bi - 1].lo if bi else 1.0,
            "points": band.points,
            "n": n,
            "n_played": k,
            "songs_per_show": n / n_shows if n_shows else 0.0,
        }
        if n:
            rate = k / n
            lo, hi = wilson_interval(k, n)
            bp, by, bs = p[m], yy[m], shows[m]
            btb = None if tb is None else tb[m]
            top_hits, top_preds = [], []
            for show in np.unique(bs):
                ms = bs == show
                ps, ys = bp[ms], by[ms]
                tied = np.isclose(ps, ps.max(), rtol=0.0, atol=1e-12)
                if btb is not None:
                    ts = btb[ms]
                    tied &= np.isclose(ts, ts[tied].max(), rtol=0.0, atol=1e-12)
                top_hits.append(ys[tied].mean())
                top_preds.append(ps.max())
            top_rate = float(np.mean(top_hits))
            row.update(
                mean_pred=float(bp.mean()),
                actual_rate=rate,
                ci_low=lo,
                ci_high=hi,
                ev_at_band_points=rate * band.points,
                ev_by_points=expected_points(rate, points),
                top_pick_rate=top_rate,
                top_pick_mean_pred=float(np.mean(top_preds)),
                top_pick_ev=top_rate * band.points,
                top_pick_shows=len(top_hits),
            )
        else:
            row.update(
                mean_pred=None,
                actual_rate=None,
                ci_low=None,
                ci_high=None,
                ev_at_band_points=None,
                ev_by_points=None,
                top_pick_rate=None,
                top_pick_mean_pred=None,
                top_pick_ev=None,
                top_pick_shows=0,
            )
        out.append(row)
    return out


def summarize(probs, y, show_ids, tiebreak=None) -> dict:
    """Both band tables + reliability table + overall Brier / log loss / ECE."""
    p = np.asarray(probs, dtype=float)
    yy = np.asarray(y, dtype=int)
    n = len(p)
    return {
        "n_predictions": n,
        "n_shows": len(np.unique(np.asarray(show_ids))),
        "n_played": int(yy.sum()),
        "base_rate": float(yy.mean()) if n else None,
        "mean_pred": float(p.mean()) if n else None,
        "brier": brier_score(p, yy) if n else None,
        "log_loss": log_loss(p, yy) if n else None,
        "ece": expected_calibration_error(p, yy) if n else None,
        "bands": band_table(p, yy, show_ids, BANDS, tiebreak),
        "bands_4": band_table(p, yy, show_ids, PROPOSED_BANDS, tiebreak),
        "reliability": reliability_table(p, yy),
    }


def per_show_totals(probs, y, show_ids, played_all: dict | None = None) -> dict:
    """Per show: summed chances vs candidate songs actually played (and, if
    given, every song played, candidates or not)."""
    p = np.asarray(probs, dtype=float)
    yy = np.asarray(y, dtype=float)
    shows = np.asarray(show_ids)
    uniq, inv = np.unique(shows, return_inverse=True)
    sum_p = np.bincount(inv, weights=p, minlength=len(uniq))
    sum_y = np.bincount(inv, weights=yy, minlength=len(uniq))
    out = {
        "n_shows": len(uniq),
        "mean_sum_pred": float(sum_p.mean()) if len(uniq) else None,
        "mean_played_candidates": float(sum_y.mean()) if len(uniq) else None,
        "mean_abs_gap": float(np.abs(sum_p - sum_y).mean()) if len(uniq) else None,
    }
    if played_all is not None:
        out["mean_played_all"] = float(np.mean([played_all[s] for s in uniq.tolist()]))
    return out


def nested_calibration(
    probs, y, dates, block, block_starts, eval_from: int, calibration_days: int
) -> tuple[np.ndarray, list[dict]]:
    """Calibrate every block starting on/after `eval_from` with an isotonic
    map fitted only on rows dated in [block start - calibration_days, block
    start). Rows outside those blocks come back NaN."""
    p = np.asarray(probs, dtype=float)
    yy = np.asarray(y, dtype=int)
    d = np.asarray(dates, dtype=int)
    blk = np.asarray(block)
    out = np.full(len(p), np.nan)
    fits = []
    for b, start in enumerate(block_starts):
        if start < eval_from:
            continue
        in_block = blk == b
        fit = (d < start) & (d >= start - calibration_days)
        if not fit.any():  # nothing earlier to learn from: leave the chances as they are
            out[in_block] = p[in_block]
            fits.append({"block": b, "start": date.fromordinal(start).isoformat(), "fitted": False})
            continue
        x, yk = fit_isotonic(p[fit], yy[fit])
        out[in_block] = InclusionCalibration(x=x, y=yk).apply(p[in_block])
        fits.append(
            {
                "block": b,
                "start": date.fromordinal(start).isoformat(),
                "fitted": True,
                "fit_from": date.fromordinal(int(d[fit].min())).isoformat(),
                "fit_through": date.fromordinal(int(d[fit].max())).isoformat(),
                "n_predictions": int(fit.sum()),
                "n_knots": len(x),
            }
        )
    return out, fits


# --------------------------------------------------------- DB-backed parts


def frequency_baseline(hist: InclusionHistory, rows: InclusionRows) -> np.ndarray:
    """Each song's play rate over the 365 days before the show: plays /
    shows-with-a-setlist in that window, using only earlier shows. The
    numerator is the model's own `plays_last_12mo` feature (same window)."""
    p12 = rows.X[:, INCLUSION_FEATURE_COLUMNS.index("plays_last_12mo")]
    setlist_ords = sorted(
        hist.context_for(sid).show_date.toordinal()
        for sid, songs in hist.played_in_show.items()
        if songs
    )
    n_prior = {}
    for d in np.unique(rows.dates).tolist():
        n_prior[d] = bisect.bisect_left(setlist_ords, d) - bisect.bisect_left(setlist_ords, d - 365)
    denom = np.array([n_prior[d] for d in rows.dates.tolist()], dtype=float)
    return np.divide(p12, denom, out=np.zeros_like(p12), where=denom > 0)


def _slice_stats(probs, y, show_ids) -> dict:
    p, yy = np.asarray(probs, dtype=float), np.asarray(y, dtype=int)
    n, k = len(p), int(yy.sum())
    lo, hi = wilson_interval(k, n)
    return {
        "n_predictions": n,
        "n_shows": len(np.unique(np.asarray(show_ids))),
        "n_played": k,
        "mean_pred": float(p.mean()) if n else None,
        "actual_rate": k / n if n else None,
        "ci_low": lo if n else None,
        "ci_high": hi if n else None,
    }


def _coverage(hist: InclusionHistory, show_ids, song_ids) -> dict:
    """How many actually-played (show, song) pairs the candidate set covers,
    and how often the songs outside it (played before, but not in the last
    UNIVERSE_YEARS) turn up — the true long shots the model never prices."""
    cands: dict[int, set[int]] = defaultdict(set)
    for s, g in zip(np.asarray(show_ids).tolist(), np.asarray(song_ids).tolist(), strict=True):
        cands[s].add(g)
    first_play = sorted(ms[0]["ord"] for ms in hist.plays.values() if ms)
    played = in_cands = debut = stale = older = 0
    for s, songs in cands.items():
        d = hist.context_for(s).show_date.toordinal()
        older += bisect.bisect_left(first_play, d) - len(songs)
        for g in hist.played_in_show[s]:
            played += 1
            if g in songs:
                in_cands += 1
            elif not hist.plays[g] or hist.plays[g][0]["ord"] >= d:
                debut += 1  # first-ever play (nothing strictly before tonight)
            else:
                stale += 1  # last played more than UNIVERSE_YEARS ago
    return {
        "played_pairs": played,
        "played_pairs_in_candidates": in_cands,
        "share_in_candidates": in_cands / played if played else None,
        "share_unpriced": (played - in_cands) / played if played else None,
        "missed_debuts": debut,
        f"missed_not_played_in_{UNIVERSE_YEARS}y": stale,
        "candidates_per_show": float(np.mean([len(v) for v in cands.values()])) if cands else 0.0,
        "older_songs_per_show": older / len(cands) if cands else 0.0,
        "older_song_play_rate": stale / older if older else None,
    }


def _period_report(
    hist: InclusionHistory,
    rows: InclusionRows,
    ridx: np.ndarray,
    raw: np.ndarray,
    adjusted: np.ndarray,
    calibrated: np.ndarray,
    baseline: np.ndarray,
    flags: np.ndarray,
) -> dict:
    y, shows = rows.y[ridx], rows.show_ids[ridx]
    played_all = {s: len(hist.played_in_show[s]) for s in np.unique(shows).tolist()}
    nights_2plus = np.unique(shows[flags])
    rest = np.isin(shows, nights_2plus) & ~flags
    dates = rows.dates[ridx]
    return {
        "from": date.fromordinal(int(dates.min())).isoformat(),
        "through": date.fromordinal(int(dates.max())).isoformat(),
        "raw": summarize(raw, y, shows),
        "run_rule": summarize(adjusted, y, shows),
        "calibrated": summarize(calibrated, y, shows, tiebreak=adjusted),
        "baseline": summarize(baseline, y, shows),
        "totals": {
            "raw": per_show_totals(raw, y, shows, played_all),
            "run_rule": per_show_totals(adjusted, y, shows, played_all),
            "calibrated": per_show_totals(calibrated, y, shows, played_all),
        },
        "coverage": _coverage(hist, shows, rows.song_ids[ridx]),
        "run_slice": {
            "n_shows_nights_2plus": len(nights_2plus),
            "raw": _slice_stats(raw[flags], y[flags], shows[flags]),
            "run_rule": _slice_stats(adjusted[flags], y[flags], shows[flags]),
            "calibrated": _slice_stats(calibrated[flags], y[flags], shows[flags]),
            "raw_other_songs_same_nights": _slice_stats(raw[rest], y[rest], shows[rest]),
            "calibrated_other_songs_same_nights": _slice_stats(
                calibrated[rest], y[rest], shows[rest]
            ),
        },
    }


def _jsonable(obj):
    """Numpy scalars -> Python; NaN/inf -> None; int dict keys kept (json
    stringifies them)."""
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.integer | np.bool_):
        return obj.item()
    if isinstance(obj, float | np.floating):
        f = float(obj)
        return f if math.isfinite(f) else None
    return obj


def run_calibration(
    db_path: Path,
    cutoff: str,
    out_dir: Path,
    recent_from: str | None = None,
    artifact_path: Path | None = None,
    artifact_trained_through: str | None = None,
    num_boost_round: int = 300,
    warmup_shows: int = 50,
    block_shows: int = DEFAULT_BLOCK_SHOWS,
    calibration_days: int = DEFAULT_CALIBRATION_DAYS,
) -> dict:
    """Run the nested backtest on shows dated on/after `cutoff`; write
    `inclusion_calibration.json`, `summary.txt` and (when matplotlib is
    installed) `reliability.png` to `out_dir`."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cutoff_ord = date.fromisoformat(cutoff).toordinal()

    conn = open_db(Path(db_path), read_only=True)
    try:
        hist = InclusionHistory(conn)
        rows = build_inclusion_rows(hist, warmup_shows=warmup_shows)
    finally:
        conn.close()
    flags_all = played_earlier_in_run(hist, rows.show_ids, rows.song_ids)
    baseline_all = frequency_baseline(hist, rows)

    # Walk-forward chances from a calibration window before the cutoff, with
    # a block boundary at the cutoff so no evaluated block straddles it.
    wf = walk_forward(
        rows,
        flags_all,
        cutoff_ord - calibration_days,
        block_shows=block_shows,
        num_boost_round=num_boost_round,
        breaks=(cutoff_ord,),
    )
    idx = wf.rows_idx
    y, d = rows.y[idx], rows.dates[idx]
    if not len(idx) or not (d >= cutoff_ord).any():
        raise ValueError(f"cutoff {cutoff} leaves no shows to evaluate")
    calibrated, fits = nested_calibration(
        wf.adjusted,
        y,
        d,
        wf.block,
        [b["start_ord"] for b in wf.blocks],
        cutoff_ord,
        calibration_days,
    )

    last_ord = int(d.max())
    recent_ord = (
        date.fromisoformat(recent_from).toordinal() if recent_from else last_ord - RECENT_DAYS
    )
    recent_ord = max(recent_ord, cutoff_ord)
    periods = {}
    for name, from_ord in (("full", cutoff_ord), ("recent", recent_ord)):
        m = d >= from_ord
        if not m.any():
            periods[name] = None
            continue
        periods[name] = _period_report(
            hist,
            rows,
            idx[m],
            wf.raw[m],
            wf.adjusted[m],
            calibrated[m],
            baseline_all[idx[m]],
            flags_all[idx[m]],
        )

    result: dict = {
        "config": {
            "db": str(db_path),
            "cutoff": cutoff,
            "recent_from": date.fromordinal(recent_ord).isoformat(),
            "num_boost_round": num_boost_round,
            "warmup_shows": warmup_shows,
            "block_shows": block_shows,
            "calibration_days": calibration_days,
            "run_repeat_chance": RUN_REPEAT_CHANCE,
            "lgb_params": _PARAMS,
            "bands": [{"name": b.name, "lo": b.lo, "points": b.points} for b in BANDS],
            "bands_4": [{"name": b.name, "lo": b.lo, "points": b.points} for b in PROPOSED_BANDS],
            "reliability_edges": list(RELIABILITY_EDGES),
            "log_loss_eps": LOG_LOSS_EPS,
            "baseline": "plays in the 365 days before the show / shows with a setlist "
            "in that window (earlier shows only)",
            "run_definition": "same venue_id + tour_id, earlier show (app residency)",
            "candidate_set": f"songs with >=1 play in the {UNIVERSE_YEARS} years before "
            "the show (model's own universe)",
            "method": "walk-forward: retrain on all shows dated before each block, "
            "predict the block; run rule; isotonic fitted on the walk-forward chances "
            "of the calibration_days before each block",
        },
        "walk_forward_blocks": wf.blocks,
        "calibration_fits": fits,
        "periods": periods,
        "production_artifact": None,
    }

    if artifact_path is not None:
        if artifact_trained_through is None:
            raise ValueError("artifact_trained_through is required with artifact_path")
        scorer = LightGBMScorer.load(Path(artifact_path))
        cols = [INCLUSION_FEATURE_COLUMNS.index(c) for c in scorer.feature_columns]
        after = d > date.fromisoformat(artifact_trained_through).toordinal()
        if not after.any():
            raise ValueError(f"no evaluated shows after {artifact_trained_through}")
        ridx = idx[after]
        p_art = scorer.score(rows.X[ridx][:, cols])
        p_art_rr = apply_run_rule(p_art, flags_all[ridx])
        ya, sa = rows.y[ridx], rows.show_ids[ridx]
        art = summarize(p_art, ya, sa)
        result["production_artifact"] = {
            "path": str(artifact_path),
            "sha256": file_sha256(Path(artifact_path)),
            "feature_columns_match_current": list(scorer.feature_columns)
            == INCLUSION_FEATURE_COLUMNS,
            "trained_through": artifact_trained_through,
            "n_shows": art["n_shows"],
            "from": date.fromordinal(int(d[after].min())).isoformat(),
            "through": date.fromordinal(int(d[after].max())).isoformat(),
            "artifact": art,
            "artifact_run_rule": summarize(p_art_rr, ya, sa),
            "walk_forward_calibrated_same_shows": summarize(
                calibrated[after], ya, sa, tiebreak=wf.adjusted[after]
            ),
        }

    result["chart"] = _write_chart(out_dir / "reliability.png", result)
    result = _jsonable(result)
    (out_dir / "inclusion_calibration.json").write_text(json.dumps(result, indent=2))
    (out_dir / "summary.txt").write_text(format_report(result))
    return result


# ------------------------------------------------------------------ output


# Reference palette (dataviz skill), light mode: categorical slots 1-3 in
# fixed order (validated all-pairs); colour follows the entity across panels.
_SURFACE = "#fcfcfb"
_INK, _INK_2, _GRID = "#0b0b0b", "#52514e", "#e4e3df"
_SERIES = (
    ("raw", "Raw model", "#2a78d6"),  # slot 1 blue
    ("run_rule", "Run rule", "#eb6834"),  # slot 2 orange
    ("calibrated", "Run rule + calibrated", "#1baf7a"),  # slot 3 aqua
)


def _write_chart(path: Path, result: dict) -> dict:
    """Reliability diagrams (full period, recent slice) as small multiples.
    Skipped (with the reason) when matplotlib isn't installed — it is not a
    project dependency."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return {"path": None, "skipped": "matplotlib not installed"}

    panels = [
        (
            f"{label} {p['from']} to {p['through']} ({p['raw']['n_shows']} shows)",
            p,
        )
        for label, p in (
            ("All test shows,", result["periods"]["full"]),
            ("Recent,", result["periods"]["recent"]),
        )
        if p is not None
    ]
    ticks = [0.0, 0.01, 0.05, 0.15, 0.35, 0.6, 1.0]
    tick_labels = ["0", "1%", "5%", "15%", "35%", "60%", "100%"]
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": _GRID, "text.color": _INK})
    fig, axes = plt.subplots(
        1, len(panels), figsize=(4.6 * len(panels), 4.8), dpi=150, facecolor=_SURFACE
    )
    for ax, (title, period) in zip(np.atleast_1d(axes), panels, strict=True):
        ax.set_facecolor(_SURFACE)
        ax.set_xscale("function", functions=(np.sqrt, np.square))
        ax.set_yscale("function", functions=(np.sqrt, np.square))
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.plot([0, 1], [0, 1], color=_INK_2, lw=1, ls=(0, (4, 3)), zorder=1)
        for edge in (0.01, 0.05, 0.15, 0.35):
            ax.axvline(edge, color=_GRID, lw=0.8, zorder=0)
        for key, label, color in _SERIES:
            pts = [r for r in period[key]["reliability"] if r["n"]]
            x = [r["mean_pred"] for r in pts]
            yv = [r["actual_rate"] for r in pts]
            err = [
                [r["actual_rate"] - r["ci_low"] for r in pts],
                [r["ci_high"] - r["actual_rate"] for r in pts],
            ]
            ax.errorbar(
                x, yv, yerr=err, fmt="none", ecolor=color, elinewidth=1, alpha=0.45, zorder=2
            )
            ece = 100 * period[key]["ece"]
            ax.plot(
                x,
                yv,
                color=color,
                lw=2,
                marker="o",
                ms=5,
                mec=_SURFACE,
                mew=1.2,
                label=f"{label} (ECE {ece:.2f} pts)",
                zorder=3,
            )
        ax.set_xticks(ticks, tick_labels, color=_INK_2)
        ax.set_yticks(ticks, tick_labels, color=_INK_2)
        ax.tick_params(length=0)
        ax.grid(axis="y", color=_GRID, lw=0.8)
        ax.set_title(title, fontsize=9, color=_INK, loc="left")
        ax.set_xlabel("Predicted chance (bin mean)", color=_INK_2)
        ax.legend(loc="upper left", frameon=False, fontsize=8, labelcolor=_INK)
        for spine in ax.spines.values():
            spine.set_visible(False)
    np.atleast_1d(axes)[0].set_ylabel("Actually played (95% Wilson)", color=_INK_2)
    fig.suptitle(
        "Likely Tonight, walk-forward out of sample: predicted vs actual "
        "(dashed = honest; sqrt axes; gridlines at band edges)",
        fontsize=10,
        color=_INK,
        x=0.01,
        ha="left",
    )
    fig.tight_layout()
    fig.savefig(path, facecolor=_SURFACE)
    plt.close(fig)
    return {"path": str(path), "skipped": None}


def _pct(v) -> str:
    return "   -  " if v is None else f"{100 * v:5.1f}%"


def _band_lines(bands: list[dict]) -> list[str]:
    lines = [
        f"    {'band':<10} {'n':>6} {'/show':>6} {'pred':>7} {'actual':>7} "
        f"{'95% CI':>15} {'pts':>4} {'EV/pick':>7} {'top pred/act':>15} {'top EV':>6}"
    ]
    for b in bands:
        ci = f"{_pct(b['ci_low'])}-{_pct(b['ci_high']).strip()}" if b["n"] else "      -"
        ev = f"{b['ev_at_band_points']:7.2f}" if b["n"] else "      -"
        top_ev = f"{b['top_pick_ev']:6.2f}" if b["n"] else "     -"
        lines.append(
            f"    {b['band']:<10} {b['n']:>6} {b['songs_per_show']:>6.1f} "
            f"{_pct(b['mean_pred']):>7} {_pct(b['actual_rate']):>7} {ci:>15} "
            f"{b['points']:>4} {ev} {_pct(b['top_pick_mean_pred']):>7}/"
            f"{_pct(b['top_pick_rate']):>7} {top_ev}"
        )
    return lines


def _metric_line(name: str, s: dict) -> str:
    return (
        f"    {name}: Brier {s['brier']:.5f}  log loss {s['log_loss']:.5f}  "
        f"ECE {100 * s['ece']:.2f} pts  (mean pred {_pct(s['mean_pred'])}, "
        f"actual {_pct(s['base_rate'])}, n={s['n_predictions']}, shows={s['n_shows']})"
    )


def _period_lines(name: str, p: dict) -> list[str]:
    cov = p["coverage"]
    lines = [
        f"{name.upper()} ({p['from']}..{p['through']}, {p['raw']['n_shows']} shows, "
        f"{p['raw']['n_predictions']} predictions)",
        f"  coverage: {cov['played_pairs_in_candidates']}/{cov['played_pairs']} played songs "
        f"were candidates; unpriced {_pct(cov['share_unpriced']).strip()} "
        f"({cov['missed_debuts']} debuts + {cov[f'missed_not_played_in_{UNIVERSE_YEARS}y']} "
        f"older bustouts); {cov['older_songs_per_show']:.0f} older songs/show play at "
        f"{_pct(cov['older_song_play_rate']).strip()} each",
        "  per show: summed chances vs songs played "
        f"(candidates {p['totals']['raw']['mean_played_candidates']:.1f}, "
        f"all {p['totals']['raw']['mean_played_all']:.1f})",
    ]
    for key in ("raw", "run_rule", "calibrated"):
        t = p["totals"][key]
        lines.append(
            f"    {key:<10} sum {t['mean_sum_pred']:5.1f}  mean |gap| {t['mean_abs_gap']:.1f}"
        )
    for key, label in (
        ("raw", "raw"),
        ("run_rule", "run rule"),
        ("calibrated", "run rule + calibrated"),
    ):
        lines += [f"  5 bands, {label}:", *_band_lines(p[key]["bands"]), _metric_line(key, p[key])]
    lines.append(_metric_line("baseline (12-month rate)", p["baseline"]))
    lines += [
        "  PROPOSED 4 bands, run rule + calibrated:",
        *_band_lines(p["calibrated"]["bands_4"]),
    ]
    lines += ["  PROPOSED 4 bands, raw:", *_band_lines(p["raw"]["bands_4"])]
    rs = p["run_slice"]
    lines.append(
        f"  run slice ({rs['n_shows_nights_2plus']} nights 2+), songs already played this run:"
    )
    for key in ("raw", "run_rule", "calibrated"):
        s = rs[key]
        lines.append(
            f"    {key:<10} n={s['n_predictions']} mean pred {_pct(s['mean_pred'])} "
            f"actual {_pct(s['actual_rate'])}"
        )
    return lines


def format_report(r: dict) -> str:
    fits = [f for f in r["calibration_fits"] if f.get("fitted")]
    cfg = r["config"]
    lines = [
        "Likely Tonight calibration backtest (walk-forward, nested calibration)",
        f"blocks of {cfg['block_shows']} shows; {len(r['walk_forward_blocks'])} retrains; "
        f"{len(fits)} calibration fits on the prior {cfg['calibration_days']} days "
        f"(median {int(np.median([f['n_predictions'] for f in fits])) if fits else 0} "
        f"predictions each); run-repeat cap {_pct(cfg['run_repeat_chance']).strip()}",
        "",
    ]
    for name in ("recent", "full"):
        if r["periods"][name] is not None:
            lines += _period_lines(name, r["periods"][name]) + [""]
    art = r["production_artifact"]
    if art:
        lines += [
            f"PRODUCTION ARTIFACT (sha256 {art['sha256'][:12]}), shows after "
            f"{art['trained_through']} ({art['from']}..{art['through']}, {art['n_shows']} shows)",
            _metric_line("artifact raw", art["artifact"]),
            _metric_line("artifact + run rule", art["artifact_run_rule"]),
            _metric_line("walk-forward calibrated", art["walk_forward_calibrated_same_shows"]),
            "",
        ]
    chart = r["chart"]
    lines.append(f"chart: {chart['path'] or 'skipped (' + chart['skipped'] + ')'}")
    return "\n".join(lines) + "\n"
