"""Calibration backtest for the show-level 'Likely Tonight' inclusion model.

The question: when the model says a song has an 8% chance of being played
anywhere tonight, is it played about 8% of the time? That decides whether a
"bonus pick" (one song per show, scored if played anywhere, points by
likelihood band) can be priced on these chances.

Method: train with the production params on shows before a cutoff, score
every candidate for every later show (features use only plays strictly before
the show — see `inclusion_features`), and compare predicted chances with what
happened, by bonus band and in finer reliability bins. Alongside: a trailing
12-month play-rate baseline, a "played earlier in this run" slice, an
isotonic recalibration experiment, and an out-of-sample check of a saved
production artifact.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from phishpicker.db.connection import open_db
from phishpicker.model.lightgbm_scorer import LightGBMScorer
from phishpicker.train.inclusion_features import (
    INCLUSION_FEATURE_COLUMNS,
    UNIVERSE_YEARS,
    InclusionHistory,
    InclusionRows,
    build_inclusion_rows,
)
from phishpicker.train.inclusion_runner import _PARAMS, fit_inclusion_booster


@dataclass(frozen=True)
class Band:
    name: str
    lo: float  # inclusive lower edge
    points: int  # proposed bonus points for a correct pick in this band


# The proposed bonus bands, most likely first.
BANDS: tuple[Band, ...] = (
    Band("Safe bet", 0.35, 5),
    Band("Good bet", 0.15, 10),
    Band("Long shot", 0.05, 20),
    Band("Deep cut", 0.01, 40),
    Band("Wild card", 0.0, 75),
)
POINT_LEVELS: tuple[int, ...] = tuple(b.points for b in BANDS)

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

# Probability points at which to report what isotonic recalibration maps to.
_ISOTONIC_PROBES = (0.005, 0.01, 0.03, 0.05, 0.10, 0.15, 0.25, 0.35, 0.50, 0.75)


# --------------------------------------------------------------- pure parts


def assign_bands(probs) -> np.ndarray:
    """Index into BANDS for each probability (lower edges inclusive)."""
    p = np.asarray(probs, dtype=float)
    upper_los = np.array([b.lo for b in BANDS[:-1]])
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


def band_table(probs, y, show_ids) -> list[dict]:
    """Per bonus band: volume, mean predicted, actual rate (Wilson 95%), songs
    per show, expected points, and the hit rate of each show's top song in
    the band (what a player picking the band's best song would see; songs
    tied at the top count as a coin flip among them)."""
    p = np.asarray(probs, dtype=float)
    yy = np.asarray(y, dtype=int)
    shows = np.asarray(show_ids)
    n_shows = len(np.unique(shows))
    bands = assign_bands(p)
    out = []
    for bi, band in enumerate(BANDS):
        m = bands == bi
        n = int(m.sum())
        k = int(yy[m].sum())
        row = {
            "band": band.name,
            "lo": band.lo,
            "hi": BANDS[bi - 1].lo if bi else 1.0,
            "points": band.points,
            "n": n,
            "n_played": k,
            "songs_per_show": n / n_shows if n_shows else 0.0,
        }
        if n:
            rate = k / n
            lo, hi = wilson_interval(k, n)
            bp, by, bs = p[m], yy[m], shows[m]
            top_hits, top_preds = [], []
            for show in np.unique(bs):
                ps, ys = bp[bs == show], by[bs == show]
                tied = np.isclose(ps, ps.max(), rtol=0.0, atol=1e-12)
                top_hits.append(ys[tied].mean())
                top_preds.append(ps.max())
            row.update(
                mean_pred=float(bp.mean()),
                actual_rate=rate,
                ci_low=lo,
                ci_high=hi,
                ev_at_band_points=rate * band.points,
                ev_by_points=expected_points(rate),
                top_pick_rate=float(np.mean(top_hits)),
                top_pick_mean_pred=float(np.mean(top_preds)),
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
                top_pick_shows=0,
            )
        out.append(row)
    return out


def summarize(probs, y, show_ids) -> dict:
    """Band table + reliability table + overall Brier / log loss / ECE."""
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
        "bands": band_table(p, yy, show_ids),
        "reliability": reliability_table(p, yy),
    }


def isotonic_holdout(probs, y, show_ids, dates) -> dict:
    """Fit isotonic regression on the first half of the shows (by date) and
    apply it to the second half; report raw vs calibrated on the second half."""
    from sklearn.isotonic import IsotonicRegression

    p = np.asarray(probs, dtype=float)
    yy = np.asarray(y, dtype=int)
    shows = np.asarray(show_ids)
    ords = np.asarray(dates, dtype=int)

    show_date = {}
    for s, d in zip(shows.tolist(), ords.tolist(), strict=True):
        show_date[s] = d
    ordered = sorted(show_date, key=lambda s: (show_date[s], s))
    if len(ordered) < 2:
        raise ValueError("isotonic holdout needs at least two shows")
    n_fit = (len(ordered) + 1) // 2
    fit_shows = set(ordered[:n_fit])
    fit = np.array([s in fit_shows for s in shows.tolist()], dtype=bool)
    ev = ~fit

    iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
    iso.fit(p[fit], yy[fit])
    calibrated = iso.predict(p[ev])
    probe = iso.predict(np.array(_ISOTONIC_PROBES))
    return {
        "n_fit_shows": n_fit,
        "n_eval_shows": len(ordered) - n_fit,
        "fit_from": date.fromordinal(show_date[ordered[0]]).isoformat(),
        "fit_through": date.fromordinal(show_date[ordered[n_fit - 1]]).isoformat(),
        "eval_from": date.fromordinal(show_date[ordered[n_fit]]).isoformat(),
        "eval_through": date.fromordinal(show_date[ordered[-1]]).isoformat(),
        "mapping": [
            {"raw": float(x), "calibrated": float(c)}
            for x, c in zip(_ISOTONIC_PROBES, probe, strict=True)
        ],
        "raw": summarize(p[ev], yy[ev], shows[ev]),
        "calibrated": summarize(calibrated, yy[ev], shows[ev]),
    }


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


def played_earlier_in_run(hist: InclusionHistory, show_ids, song_ids) -> np.ndarray:
    """True where the song was already played at an earlier show of the same
    run — same venue_id + tour_id, the app's residency definition."""
    prior: dict[int, set[int]] = {}
    so_far: dict[tuple[int, int], set[int]] = defaultdict(set)
    for sh in hist.shows:  # chronological
        sid = sh["show_id"]
        ctx = hist.context_for(sid)
        if ctx.venue_id is None or ctx.tour_id is None:
            prior[sid] = set()
            continue
        key = (ctx.venue_id, ctx.tour_id)
        prior[sid] = set(so_far[key])
        so_far[key] |= hist.played_in_show.get(sid, set())
    return np.array(
        [
            song in prior.get(show, ())
            for show, song in zip(
                np.asarray(show_ids).tolist(), np.asarray(song_ids).tolist(), strict=True
            )
        ],
        dtype=bool,
    )


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
        "bands": band_table(p, yy, show_ids) if n else [],
    }


def _run_slice(hist, rows: InclusionRows, mask: np.ndarray, preds: dict[str, np.ndarray]) -> dict:
    """Nights 2+ of a run: songs already played earlier in the run vs the rest."""
    flag = played_earlier_in_run(hist, rows.show_ids[mask], rows.song_ids[mask])
    shows = rows.show_ids[mask]
    nights_2plus = np.unique(shows[flag])
    on_those_nights = np.isin(shows, nights_2plus)
    rest = on_those_nights & ~flag
    y = rows.y[mask]
    out = {"n_shows_nights_2plus": len(nights_2plus)}
    for name, p in preds.items():
        out[name] = _slice_stats(p[flag], y[flag], shows[flag])
        out[f"{name}_other_songs_same_nights"] = _slice_stats(p[rest], y[rest], shows[rest])
    return out


def _coverage(hist: InclusionHistory, rows: InclusionRows, mask: np.ndarray) -> dict:
    """How many actually-played (show, song) pairs the candidate set covers,
    and how often the songs outside it (played before, but not in the last
    UNIVERSE_YEARS) turn up — the true long shots the model never prices."""
    cands: dict[int, set[int]] = defaultdict(set)
    for s, g in zip(rows.show_ids[mask].tolist(), rows.song_ids[mask].tolist(), strict=True):
        cands[s].add(g)
    first_play = sorted(ms[0]["ord"] for ms in hist.plays.values() if ms)
    played = in_cands = debut = stale = older = 0
    for s, songs in cands.items():
        ctx = hist.context_for(s)
        d = ctx.show_date.toordinal()
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
        "missed_debuts": debut,
        f"missed_not_played_in_{UNIVERSE_YEARS}y": stale,
        "candidates_per_show": float(np.mean([len(v) for v in cands.values()])) if cands else 0.0,
        "older_songs_per_show": older / len(cands) if cands else 0.0,
        "older_song_play_rate": stale / older if older else None,
        "min_pred_rows_per_show": min((len(v) for v in cands.values()), default=0),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
    artifact_path: Path | None = None,
    artifact_trained_through: str | None = None,
    num_boost_round: int = 300,
    warmup_shows: int = 50,
) -> dict:
    """Run the whole backtest; write `inclusion_calibration.json`, `summary.txt`
    and (when matplotlib is installed) `reliability.png` to `out_dir`."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cutoff_ord = date.fromisoformat(cutoff).toordinal()

    conn = open_db(Path(db_path), read_only=True)
    try:
        hist = InclusionHistory(conn)
        rows = build_inclusion_rows(hist, warmup_shows=warmup_shows)
    finally:
        conn.close()

    train = rows.dates < cutoff_ord
    test = ~train
    if not train.any() or not test.any():
        raise ValueError(f"cutoff {cutoff} leaves no training or no test shows")

    booster = fit_inclusion_booster(rows.X[train], rows.y[train], num_boost_round)
    p_all = booster.predict(rows.X)  # train rows unused except for the artifact check
    base_all = frequency_baseline(hist, rows)

    y_t, s_t, d_t = rows.y[test], rows.show_ids[test], rows.dates[test]
    p_t, b_t = p_all[test], base_all[test]
    model = summarize(p_t, y_t, s_t)
    baseline = summarize(b_t, y_t, s_t)

    result: dict = {
        "config": {
            "db": str(db_path),
            "cutoff": cutoff,
            "num_boost_round": num_boost_round,
            "warmup_shows": warmup_shows,
            "lgb_params": _PARAMS,
            "bands": [{"name": b.name, "lo": b.lo, "points": b.points} for b in BANDS],
            "reliability_edges": list(RELIABILITY_EDGES),
            "log_loss_eps": LOG_LOSS_EPS,
            "baseline": "plays in the 365 days before the show / shows with a setlist "
            "in that window (earlier shows only)",
            "run_definition": "same venue_id + tour_id, earlier show (app residency)",
            "candidate_set": f"songs with >=1 play in the {UNIVERSE_YEARS} years before "
            "the show (model's own universe)",
        },
        "n_train_rows": int(train.sum()),
        "n_train_shows": len(np.unique(rows.show_ids[train])),
        "train_from": date.fromordinal(int(rows.dates[train].min())).isoformat(),
        "train_through": date.fromordinal(int(rows.dates[train].max())).isoformat(),
        "n_test_shows": model["n_shows"],
        "n_test_predictions": model["n_predictions"],
        "test_from": date.fromordinal(int(d_t.min())).isoformat(),
        "test_through": date.fromordinal(int(d_t.max())).isoformat(),
        "coverage": _coverage(hist, rows, test),
        "model": model,
        "baseline": baseline,
        "model_beats_baseline": {m: model[m] < baseline[m] for m in ("brier", "log_loss", "ece")},
        "run_slice": _run_slice(hist, rows, test, {"model": p_t, "baseline": b_t}),
        "isotonic": isotonic_holdout(p_t, y_t, s_t, d_t),
        "production_artifact": None,
    }

    if artifact_path is not None:
        if artifact_trained_through is None:
            raise ValueError("artifact_trained_through is required with artifact_path")
        scorer = LightGBMScorer.load(Path(artifact_path))
        cols = [INCLUSION_FEATURE_COLUMNS.index(c) for c in scorer.feature_columns]
        after = rows.dates > date.fromisoformat(artifact_trained_through).toordinal()
        if not after.any():
            raise ValueError(f"no shows with a setlist after {artifact_trained_through}")
        p_art = scorer.score(rows.X[after][:, cols])
        ya, sa = rows.y[after], rows.show_ids[after]
        art = summarize(p_art, ya, sa)
        result["production_artifact"] = {
            "path": str(artifact_path),
            "sha256": _sha256(Path(artifact_path)),
            "feature_columns_match_current": list(scorer.feature_columns)
            == INCLUSION_FEATURE_COLUMNS,
            "trained_through": artifact_trained_through,
            "n_shows": art["n_shows"],
            "from": date.fromordinal(int(rows.dates[after].min())).isoformat(),
            "through": date.fromordinal(int(rows.dates[after].max())).isoformat(),
            "artifact": art,
            "backtest_model_same_shows": summarize(p_all[after], ya, sa),
            "backtest_model_is_out_of_sample_here": bool(rows.dates[after].min() >= cutoff_ord),
            "baseline_same_shows": summarize(base_all[after], ya, sa),
            "run_slice": _run_slice(
                hist, rows, after, {"artifact": p_art, "backtest_model": p_all[after]}
            ),
        }

    result["chart"] = _write_chart(out_dir / "reliability.png", result)
    result = _jsonable(result)
    (out_dir / "inclusion_calibration.json").write_text(json.dumps(result, indent=2))
    (out_dir / "summary.txt").write_text(format_report(result))
    return result


# ------------------------------------------------------------------ output


# Reference palette (dataviz skill), light mode: categorical slots in fixed
# order; colour follows the entity across panels.
_SURFACE = "#fcfcfb"
_INK, _INK_2, _GRID = "#0b0b0b", "#52514e", "#e4e3df"
_COLOR = {
    "Backtest model": "#2a78d6",  # slot 1 blue
    "12-month play rate": "#eb6834",  # slot 2 orange
    "Production artifact": "#1baf7a",  # slot 3 aqua
    "Isotonic-calibrated": "#eda100",  # slot 4 yellow
}


def _write_chart(path: Path, result: dict) -> dict:
    """Reliability diagrams as small multiples. Skipped (with the reason)
    when matplotlib isn't installed — it is not a project dependency."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return {"path": None, "skipped": "matplotlib not installed"}

    panels = [
        (
            f"Test period {result['test_from']} to {result['test_through']}\n"
            f"({result['n_test_shows']} shows)",
            [
                ("Backtest model", result["model"]["reliability"]),
                ("12-month play rate", result["baseline"]["reliability"]),
            ],
        ),
        (
            f"Second half {result['isotonic']['eval_from']} on\n(isotonic fitted on first half)",
            [
                ("Backtest model", result["isotonic"]["raw"]["reliability"]),
                ("Isotonic-calibrated", result["isotonic"]["calibrated"]["reliability"]),
            ],
        ),
    ]
    art = result.get("production_artifact")
    if art:
        panels.append(
            (
                f"After {art['trained_through']}: production artifact\n"
                f"({art['n_shows']} shows, out of sample)",
                [
                    ("Production artifact", art["artifact"]["reliability"]),
                    ("Backtest model", art["backtest_model_same_shows"]["reliability"]),
                ],
            )
        )

    ticks = [0.0, 0.01, 0.05, 0.15, 0.35, 0.6, 1.0]
    tick_labels = ["0", "1%", "5%", "15%", "35%", "60%", "100%"]
    fwd, inv = (np.sqrt, np.square)
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": _GRID, "text.color": _INK})
    fig, axes = plt.subplots(
        1, len(panels), figsize=(4.2 * len(panels), 4.6), dpi=150, facecolor=_SURFACE
    )
    for ax, (title, series) in zip(np.atleast_1d(axes), panels, strict=True):
        ax.set_facecolor(_SURFACE)
        ax.set_xscale("function", functions=(fwd, inv))
        ax.set_yscale("function", functions=(fwd, inv))
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.plot([0, 1], [0, 1], color=_INK_2, lw=1, ls=(0, (4, 3)), zorder=1)
        for edge in (0.01, 0.05, 0.15, 0.35):
            ax.axvline(edge, color=_GRID, lw=0.8, zorder=0)
        for label, rel in series:
            pts = [r for r in rel if r["n"]]
            x = [r["mean_pred"] for r in pts]
            yv = [r["actual_rate"] for r in pts]
            err = [
                [r["actual_rate"] - r["ci_low"] for r in pts],
                [r["ci_high"] - r["actual_rate"] for r in pts],
            ]
            c = _COLOR[label]
            ax.errorbar(x, yv, yerr=err, fmt="none", ecolor=c, elinewidth=1, alpha=0.45, zorder=2)
            ax.plot(
                x,
                yv,
                color=c,
                lw=2,
                marker="o",
                ms=5,
                mec=_SURFACE,
                mew=1.2,
                label=label,
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
        "Likely Tonight: predicted vs actual (dashed = perfectly honest; "
        "sqrt axes; gridlines at band edges)",
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


def _band_lines(summary: dict) -> list[str]:
    lines = [
        f"  {'band':<10} {'n':>6} {'/show':>6} {'pred':>7} {'actual':>7} "
        f"{'95% CI':>15} {'top pick pred/act':>17}  EV@5/10/20/40/75 (own band *)"
    ]
    for b in summary["bands"]:
        ci = f"{_pct(b['ci_low'])}-{_pct(b['ci_high']).strip()}" if b["n"] else "      -"
        evs = (
            " ".join(
                f"{v:5.2f}{'*' if int(k) == b['points'] else ' '}"
                for k, v in b["ev_by_points"].items()
            )
            if b["ev_by_points"]
            else "-"
        )
        lines.append(
            f"  {b['band']:<10} {b['n']:>6} {b['songs_per_show']:>6.1f} {_pct(b['mean_pred']):>7} "
            f"{_pct(b['actual_rate']):>7} {ci:>15} "
            f"{_pct(b['top_pick_mean_pred']):>8}/{_pct(b['top_pick_rate']):>8}  {evs}"
        )
    return lines


def _metric_line(name: str, s: dict) -> str:
    return (
        f"  {name}: Brier {s['brier']:.5f}  log loss {s['log_loss']:.5f}  "
        f"ECE {100 * s['ece']:.2f} pts  (mean pred {_pct(s['mean_pred'])}, "
        f"actual {_pct(s['base_rate'])}, n={s['n_predictions']}, shows={s['n_shows']})"
    )


def format_report(r: dict) -> str:
    cov = r["coverage"]
    lines = [
        "Likely Tonight calibration backtest",
        f"cutoff {r['config']['cutoff']}: trained on {r['n_train_shows']} shows "
        f"({r['train_from']}..{r['train_through']}); tested on {r['n_test_shows']} shows "
        f"({r['test_from']}..{r['test_through']}), {r['n_test_predictions']} predictions",
        f"coverage: {cov['played_pairs_in_candidates']}/{cov['played_pairs']} played songs were "
        f"candidates ({_pct(cov['share_in_candidates']).strip()}); missed "
        f"{cov['missed_debuts']} debuts + {cov[f'missed_not_played_in_{UNIVERSE_YEARS}y']} "
        f"older bustouts; {cov['candidates_per_show']:.0f} candidates/show",
        f"outside the candidate set: {cov['older_songs_per_show']:.0f} previously-played "
        f"songs/show, played at {_pct(cov['older_song_play_rate']).strip()} each",
        "",
        "MODEL (trained before cutoff)",
        *_band_lines(r["model"]),
        _metric_line("overall", r["model"]),
        "",
        "BASELINE (12-month play rate)",
        *_band_lines(r["baseline"]),
        _metric_line("overall", r["baseline"]),
        "  model beats baseline: "
        + ", ".join(f"{k} {'yes' if v else 'NO'}" for k, v in r["model_beats_baseline"].items()),
        "",
    ]
    rs = r["run_slice"]
    lines += [
        f"RUN SLICE (nights 2+ of a run; {rs['n_shows_nights_2plus']} shows)",
    ]
    for key, label in (
        ("model", "model, already played this run"),
        ("model_other_songs_same_nights", "model, other songs same nights"),
        ("baseline", "baseline, already played this run"),
    ):
        s = rs[key]
        lines.append(
            f"  {label}: n={s['n_predictions']} mean pred {_pct(s['mean_pred'])} "
            f"actual {_pct(s['actual_rate'])} (CI {_pct(s['ci_low'])}-{_pct(s['ci_high'])})"
        )
    already = {b["band"]: b["n"] for b in rs["model"]["bands"]}
    lines.append(
        "  model bands for already-played songs: "
        + ", ".join(f"{k} {v}" for k, v in already.items())
    )
    iso = r["isotonic"]
    lines += [
        "",
        f"ISOTONIC (fit {iso['fit_from']}..{iso['fit_through']}, {iso['n_fit_shows']} shows; "
        f"evaluated {iso['eval_from']}..{iso['eval_through']}, {iso['n_eval_shows']} shows)",
        "  raw:",
        *_band_lines(iso["raw"]),
        _metric_line("raw", iso["raw"]),
        "  calibrated:",
        *_band_lines(iso["calibrated"]),
        _metric_line("calibrated", iso["calibrated"]),
        "  mapping: "
        + ", ".join(
            f"{_pct(m['raw']).strip()}->{_pct(m['calibrated']).strip()}" for m in iso["mapping"]
        ),
    ]
    art = r["production_artifact"]
    if art:
        lines += [
            "",
            f"PRODUCTION ARTIFACT (sha256 {art['sha256'][:12]}), shows after "
            f"{art['trained_through']} ({art['from']}..{art['through']}, {art['n_shows']} shows)",
            *_band_lines(art["artifact"]),
            _metric_line("artifact", art["artifact"]),
            _metric_line("backtest model, same shows", art["backtest_model_same_shows"]),
            _metric_line("baseline, same shows", art["baseline_same_shows"]),
        ]
        for key in ("artifact", "backtest_model"):
            s = art["run_slice"][key]
            lines.append(
                f"  run slice, {key} (already played this run): n={s['n_predictions']} "
                f"mean pred {_pct(s['mean_pred'])} actual {_pct(s['actual_rate'])}"
            )
    chart = r["chart"]
    lines += ["", f"chart: {chart['path'] or 'skipped (' + chart['skipped'] + ')'}"]
    return "\n".join(lines) + "\n"
