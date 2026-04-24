from phishpicker.live_sync import reconcile


def _u(sid, s="1", eo=1):
    return {"song_id": sid, "set_number": s, "entered_order": eo}


def _n(sid, s="1", pos=1, **kw):
    return {"song_id": sid, "set_number": s, "position": pos, **kw}


def test_append_when_net_ahead():
    actions = reconcile(
        [_u(1, "1", 1), _u(2, "1", 2)],
        [_n(1, "1", 1), _n(2, "1", 2), _n(3, "1", 3), _n(4, "1", 4)],
    )
    assert [a.kind for a in actions] == ["append", "append"]
    assert actions[0].song_id == 3
    assert actions[0].entered_order is None


def test_noop_when_aligned():
    assert (
        reconcile(
            [_u(1, "1", 1), _u(2, "1", 2)],
            [_n(1, "1", 1), _n(2, "1", 2)],
        )
        == []
    )


def test_noop_when_user_ahead():
    # user has 3 set-1 rows; phish.net has 2 — nothing to reconcile.
    assert (
        reconcile(
            [_u(1, "1", 1), _u(2, "1", 2), _u(3, "1", 3)],
            [_n(1, "1", 1), _n(2, "1", 2)],
        )
        == []
    )


def test_override_carries_real_entered_order():
    actions = reconcile(
        [_u(1, "1", 1), _u(99, "1", 2)],
        [_n(1, "1", 1), _n(2, "1", 2)],
    )
    assert len(actions) == 1
    assert actions[0].kind == "override"
    assert actions[0].set_number == "1"
    assert actions[0].position_in_set == 2
    assert actions[0].entered_order == 2
    assert actions[0].old_song_id == 99
    assert actions[0].song_id == 2


def test_entered_order_gap_after_undo_is_respected():
    # Simulates: user added 3 songs, undid the last, added a new one.
    # live_songs now has entered_orders 1, 2, 4 (3 was deleted).
    actions = reconcile(
        [_u(10, "1", 1), _u(20, "1", 2), _u(30, "1", 4)],
        [_n(10, "1", 1), _n(20, "1", 2), _n(99, "1", 3)],
    )
    assert len(actions) == 1
    assert actions[0].kind == "override"
    assert actions[0].entered_order == 4


def test_cross_set_matching_by_in_set_position():
    actions = reconcile(
        [_u(1, "1", 1), _u(2, "1", 2), _u(99, "2", 3)],
        [_n(1, "1", 1), _n(2, "1", 2), _n(77, "2", 1)],
    )
    assert len(actions) == 1
    assert actions[0].kind == "override"
    assert actions[0].set_number == "2"
    assert actions[0].position_in_set == 1
    assert actions[0].entered_order == 3
    assert actions[0].song_id == 77


def test_idempotent_when_net_uses_continuous_positions():
    # phish.net numbers positions monotonically across the whole show —
    # Set 2 starts at 9, not back at 1. Regression for a bug where the
    # reconciler indexed user rows by within-set position but net rows
    # by raw phish.net position, so user (2,1) never matched net (2,9)
    # and the same Set 2 song got appended on every 60s poll.
    user_rows = [_u(sid, "1", eo) for sid, eo in zip(range(1, 9), range(1, 9), strict=True)]
    user_rows.append(_u(575, "2", 9))  # The Curtain With already appended once
    net_rows = [_n(sid, "1", pos) for sid, pos in zip(range(1, 9), range(1, 9), strict=True)]
    net_rows.append(_n(575, "2", 9))  # phish.net reports position 9, not 1
    assert reconcile(user_rows, net_rows) == []


def test_bustout_flagged_on_append():
    actions = reconcile(
        [],
        [_n(5, "1", 1, is_unknown=True)],
    )
    assert actions[0].kind == "append"
    assert actions[0].is_bustout is True
