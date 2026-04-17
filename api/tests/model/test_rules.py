from phishpicker.model.rules import apply_post_rules


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
