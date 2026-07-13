from phishpicker.model.rules import (
    REPRISE_PENALTY,
    apply_post_rules,
    build_reprise_deps,
)

# song_id -> name for the reprise-dependency tests. 10/11 are the only two real
# reprise pairs in the catalog; 12 is a reprise whose base song does not exist.
SONG_NAMES = {
    1: "Tweezer",
    2: "Chalk Dust Torture",
    10: "Tweezer Reprise",
    11: "Chalk Dust Torture Reprise",
    12: "Orphan Reprise",
    20: "Harry Hood",
}


def test_rule_zeros_already_played_tonight():
    scored = [(100, 5.0), (101, 3.0), (102, 2.0)]
    out = apply_post_rules(scored, played_tonight={101})
    assert dict(out)[101] == 0.0
    assert dict(out)[100] == 5.0


def test_rule_preserves_all_entries():
    scored = [(100, 5.0), (101, 3.0)]
    out = apply_post_rules(scored, played_tonight=set())
    assert len(out) == 2
    assert dict(out)[100] == 5.0
    assert dict(out)[101] == 3.0


def test_rule_zeros_multiple_played_tonight():
    scored = [(100, 5.0), (101, 3.0), (102, 2.0)]
    out = apply_post_rules(scored, played_tonight={100, 102})
    d = dict(out)
    assert d[100] == 0.0
    assert d[102] == 0.0
    assert d[101] == 3.0


def test_rule_zeros_played_earlier_in_run():
    scored = [(100, 5.0), (101, 3.0), (102, 2.0)]
    out = apply_post_rules(scored, played_tonight=set(), played_in_run={101})
    d = dict(out)
    assert d[101] == 0.0
    assert d[100] == 5.0
    assert d[102] == 2.0


def test_rule_zeros_song_in_both_sets_idempotent():
    scored = [(100, 5.0), (101, 3.0)]
    out = apply_post_rules(scored, played_tonight={101}, played_in_run={101})
    assert dict(out)[101] == 0.0


def test_rule_played_in_run_defaults_to_no_filter():
    scored = [(100, 5.0), (101, 3.0)]
    out = apply_post_rules(scored, played_tonight={101})
    d = dict(out)
    assert d[101] == 0.0
    assert d[100] == 5.0


# --- reprise dependency (see docs: 91% of encore Tweezer Reprises follow a
# Tweezer earlier that same show; the remaining ~9% are standalone gags) ---


def test_build_reprise_deps_maps_reprise_to_base_song():
    deps = build_reprise_deps(SONG_NAMES)
    assert deps[10] == 1  # Tweezer Reprise -> Tweezer
    assert deps[11] == 2  # Chalk Dust Torture Reprise -> Chalk Dust Torture


def test_build_reprise_deps_skips_reprise_with_no_base_song():
    deps = build_reprise_deps(SONG_NAMES)
    assert 12 not in deps  # "Orphan Reprise" has no "Orphan" in the catalog


def test_build_reprise_deps_ignores_non_reprise_songs():
    deps = build_reprise_deps(SONG_NAMES)
    assert 1 not in deps
    assert 20 not in deps


def test_reprise_demoted_when_base_song_not_played_tonight():
    deps = build_reprise_deps(SONG_NAMES)
    scored = [(10, 5.0), (20, 3.0)]
    out = dict(apply_post_rules(scored, played_tonight=set(), reprise_deps=deps))
    assert out[10] == 5.0 * REPRISE_PENALTY
    assert out[20] == 3.0  # non-reprise untouched


def test_reprise_keeps_full_score_when_base_song_played_tonight():
    deps = build_reprise_deps(SONG_NAMES)
    scored = [(10, 5.0)]
    out = dict(apply_post_rules(scored, played_tonight={1}, reprise_deps=deps))
    assert out[10] == 5.0


def test_reprise_demote_is_soft_not_an_exclude():
    """The penalty must leave a positive score: predict_next_stateless drops
    anything at 0.0, and a hard exclude would strip Reprise from the frozen
    pre-show bracket (forfeiting exact hits like 2026-07-11 Ruoff)."""
    deps = build_reprise_deps(SONG_NAMES)
    out = dict(apply_post_rules([(10, 5.0)], played_tonight=set(), reprise_deps=deps))
    assert out[10] > 0.0


def test_reprise_still_zeroed_when_it_was_itself_already_played():
    deps = build_reprise_deps(SONG_NAMES)
    out = dict(apply_post_rules([(10, 5.0)], played_tonight={1, 10}, reprise_deps=deps))
    assert out[10] == 0.0


def test_base_song_played_earlier_in_run_does_not_satisfy_dependency():
    """The dependency is same-show, not same-run: a Tweezer two nights ago does
    not license a Tweezer Reprise tonight."""
    deps = build_reprise_deps(SONG_NAMES)
    out = dict(
        apply_post_rules(
            [(10, 5.0)], played_tonight=set(), played_in_run={1}, reprise_deps=deps
        )
    )
    assert out[10] == 5.0 * REPRISE_PENALTY


def test_no_reprise_deps_leaves_scores_unchanged():
    out = dict(apply_post_rules([(10, 5.0), (20, 3.0)], played_tonight=set()))
    assert out[10] == 5.0
    assert out[20] == 3.0
