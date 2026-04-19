import argparse
import logging
import sys

from phishpicker.config import Settings
from phishpicker.db.connection import apply_live_schema, apply_schema, open_db
from phishpicker.ingest.pipeline import run_full_ingest
from phishpicker.phishnet.client import PhishNetClient


def _configure_logging() -> None:
    """Basic stderr logging with timestamps — helps long-running `train run`
    show progress instead of looking hung for 45+ minutes."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="phishpicker")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="initialize local sqlite databases")
    p_ingest = sub.add_parser("ingest", help="full phish.net ingest")
    p_ingest.add_argument(
        "--artist-id",
        type=int,
        default=1,
        help="only ingest shows by this artist (1=Phish, 2=Trey Anastasio, "
        "6=Mike Gordon, 7=Jon Fishman, 9=Page McConnell; 0 = all artists)",
    )

    p_replay = sub.add_parser(
        "replay",
        help="side-by-side replay of two model artifacts on a historical show",
    )
    p_replay.add_argument("--model-a", required=True, help="path to model A .lgb file")
    p_replay.add_argument("--model-b", required=True, help="path to model B .lgb file")
    p_replay.add_argument("--show-id", type=int, required=True, help="historical show_id")
    p_replay.add_argument("--top-k", type=int, default=10, help="top-K candidates per slot")
    p_replay.add_argument(
        "--diff-threshold",
        type=int,
        default=5,
        help="highlight slots where rank differs by >= N between models",
    )

    p_train = sub.add_parser("train", help="training commands")
    train_sub = p_train.add_subparsers(dest="train_cmd", required=True)
    p_run = train_sub.add_parser("run", help="train + eval + ship artifacts")
    p_ab = train_sub.add_parser("ab-era", help="A/B: era-only vs era+recency weighting")
    p_ab.add_argument("--holdout", type=int, default=20)
    p_ab.add_argument("--negatives", type=int, default=50)
    p_ab.add_argument("--iterations", type=int, default=300)
    p_ab.add_argument("--seed", type=int, default=0)
    p_run.add_argument("--cutoff", default=None, help="YYYY-MM-DD (default: day after latest show)")
    p_run.add_argument("--holdout", type=int, default=20)
    p_run.add_argument("--negatives", type=int, default=50)
    p_run.add_argument("--freq-negatives", type=int, default=None)
    p_run.add_argument("--uniform-negatives", type=int, default=None)
    p_run.add_argument("--iterations", type=int, default=300)
    p_run.add_argument("--half-life-years", type=float, default=7.0)
    p_run.add_argument("--seed", type=int, default=0)
    p_run.add_argument(
        "--override",
        action="store_true",
        help="ship even if MRR regressed beyond tolerance",
    )

    args = parser.parse_args()
    _configure_logging()

    s = Settings()  # type: ignore[call-arg]

    if args.cmd == "init-db":
        conn = open_db(s.db_path)
        apply_schema(conn)
        live = open_db(s.live_db_path)
        apply_live_schema(live)
        print(f"Initialized {s.db_path} and {s.live_db_path}")
        return 0

    if args.cmd == "ingest":
        artist = None if args.artist_id == 0 else args.artist_id
        with PhishNetClient(api_key=s.phishnet_api_key, base_url=s.phishnet_base_url) as client:
            conn = open_db(s.db_path)
            stats = run_full_ingest(conn, client, artist_id=artist)
        print(f"Ingest complete (artist_id={artist}): {stats}")
        return 0

    if args.cmd == "replay":
        from pathlib import Path

        from phishpicker.replay import ReplayError, replay_show

        conn = open_db(s.db_path, read_only=True)
        try:
            result = replay_show(
                conn,
                model_a_path=Path(args.model_a),
                model_b_path=Path(args.model_b),
                show_id=args.show_id,
                top_k=args.top_k,
                diff_threshold=args.diff_threshold,
            )
        except ReplayError as exc:
            print(f"replay failed: {exc}", file=sys.stderr)
            return 2
        _print_replay(result)
        return 0

    if args.cmd == "train" and args.train_cmd == "ab-era":
        import json

        from phishpicker.train.experiments import era_ab_experiment

        conn = open_db(s.db_path, read_only=True)
        result = era_ab_experiment(
            conn,
            n_holdout_shows=args.holdout,
            negatives_per_positive=args.negatives,
            num_iterations=args.iterations,
            seed=args.seed,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.cmd == "train" and args.train_cmd == "run":
        from phishpicker.train.runner import run_training

        conn = open_db(s.db_path, read_only=True)
        result = run_training(
            conn,
            data_dir=s.data_dir,
            cutoff_date=args.cutoff,
            n_holdout_shows=args.holdout,
            negatives_per_positive=args.negatives,
            freq_negatives=args.freq_negatives,
            uniform_negatives=args.uniform_negatives,
            num_iterations=args.iterations,
            half_life_years=args.half_life_years,
            seed=args.seed,
            override_ship_gate=args.override,
        )
        if not result.get("wrote_artifacts"):
            print(
                f"Ship gate blocked: new_mrr={result.get('mrr', float('nan')):.3f} "
                f"(reason={result.get('reason', 'unknown')}). "
                f"Staged at {result.get('staging_metrics_path', '?')}. "
                "Re-run with --override to force."
            )
            return 2
        print(
            f"Trained on {result['n_shows_trained_on']} shows. "
            f"Holdout: Top-1={result['top1']:.3f} "
            f"Top-5={result['top5']:.3f} "
            f"MRR={result['mrr']:.3f} "
            f"(n={result['n_slots']})"
        )
        return 0

    return 1


def _print_replay(result: dict) -> None:
    """Format a replay_show() result for a human reader.

    One line per slot with actual-song, the rank in each model, the delta, and
    the top-3 suggestions from each model; a small summary block at the end.
    """
    show = result["show"]
    venue = show["venue_name"] or f"venue_id={show['venue_id']}"
    header = (
        f"replay: show={show['show_id']} ({show['show_date']} {venue}) — "
        f"model-a={_short(result['model_a_path'])} "
        f"model-b={_short(result['model_b_path'])}"
    )
    print(header)
    print()
    print(
        f"{'slot':>4}  {'set':>3}  {'actual':<24}  "
        f"{'rank-a':>6}  {'rank-b':>6}  {'delta':>6}  "
        f"{'top-3 A':<40}  {'top-3 B':<40}"
    )
    threshold = result["diff_threshold"]
    for s in result["slots"]:
        top_a = ", ".join(name for _sid, name in s["top_a"][:3])
        top_b = ", ".join(name for _sid, name in s["top_b"][:3])
        delta = s["delta"]
        marker = ""
        if -delta >= threshold:
            marker = "*"  # B beat A
        elif delta >= threshold:
            marker = "!"  # A beat B
        print(
            f"{s['slot']:>4}  {s['set']:>3}  {s['actual_song_name'][:24]:<24}  "
            f"{s['rank_a']:>6}  {s['rank_b']:>6}  {delta:>+5}{marker:<1}  "
            f"{top_a[:40]:<40}  {top_b[:40]:<40}"
        )
    summary = result["summary"]
    print()
    print("summary:")
    print(f"  model-a: mean rank {summary['mean_rank_a']:.1f}, MRR {summary['mrr_a']:.3f}")
    print(f"  model-b: mean rank {summary['mean_rank_b']:.1f}, MRR {summary['mrr_b']:.3f}")
    print(f"  B beat A by >={threshold} positions: {summary['b_beats_a_count']:>3} slots")
    print(f"  A beat B by >={threshold} positions: {summary['a_beats_b_count']:>3} slots")


def _short(path: str) -> str:
    """Trim a model path for the header — last two path components is plenty."""
    parts = path.rstrip("/").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else path


if __name__ == "__main__":
    sys.exit(main())
