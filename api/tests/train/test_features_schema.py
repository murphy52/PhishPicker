from phishpicker.train.features import FEATURE_COLUMNS, MISSING_INT, FeatureRow


def test_feature_row_has_song_id_and_group_id():
    row = FeatureRow.empty(song_id=1, show_id=2, slot_number=3)
    assert row.song_id == 1
    assert row.show_id == 2
    assert row.slot_number == 3


def test_feature_columns_is_stable_ordered_tuple():
    assert isinstance(FEATURE_COLUMNS, tuple)
    assert len(FEATURE_COLUMNS) >= 25
    row = FeatureRow.empty(song_id=1, show_id=2, slot_number=3)
    vec = row.to_vector()
    assert len(vec) == len(FEATURE_COLUMNS)


def test_feature_columns_are_unique():
    assert len(set(FEATURE_COLUMNS)) == len(FEATURE_COLUMNS)


def test_feature_columns_exclude_identity():
    for identity in ("song_id", "show_id", "slot_number"):
        assert identity not in FEATURE_COLUMNS


def test_feature_row_to_vector_is_all_numeric():
    row = FeatureRow.empty(song_id=1, show_id=2, slot_number=3)
    for v in row.to_vector():
        assert isinstance(v, (int, float))


def test_feature_row_missing_values_use_sentinel():
    row = FeatureRow.empty(song_id=1, show_id=2, slot_number=3)
    assert row.shows_since_last_played_anywhere == MISSING_INT


def test_to_vector_order_matches_feature_columns():
    row = FeatureRow.empty(song_id=1, show_id=2, slot_number=3)
    row.total_plays_ever = 42
    row.era = 4
    vec = row.to_vector()
    assert vec[FEATURE_COLUMNS.index("total_plays_ever")] == 42.0
    assert vec[FEATURE_COLUMNS.index("era")] == 4.0


def test_slot_type_flags_exist_and_default_to_zero():
    row = FeatureRow.empty(song_id=1, show_id=2, slot_number=3)
    assert row.is_set2 == 0
    assert row.is_first_in_set == 0
    assert "is_set2" in FEATURE_COLUMNS
    assert "is_first_in_set" in FEATURE_COLUMNS
