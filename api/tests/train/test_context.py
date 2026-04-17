import pytest

from phishpicker.db.connection import apply_schema, open_db
from phishpicker.train.context import ShowContext, compute_show_context


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path / "ctx.db")
    apply_schema(c)
    c.executescript(
        """
        INSERT INTO venues (venue_id, name) VALUES (1, 'MSG'), (2, 'Hampton');
        INSERT INTO tours (tour_id, name, start_date, end_date) VALUES
            (100, 'Summer 2024', '2024-06-01', '2024-08-31');
        INSERT INTO shows (show_id, show_date, venue_id, tour_id, tour_position, fetched_at) VALUES
            (1, '2024-06-01', 2, 100, 1, '2024-06-02'),
            (2, '2024-06-03', 2, 100, 2, '2024-06-04'),
            (3, '2024-07-04', 1, 100, 10, '2024-07-05');
        """
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_era_derived_from_date_2024_is_4(conn):
    ctx = compute_show_context(conn, show_date="2024-06-01", venue_id=2)
    assert isinstance(ctx, ShowContext)
    assert ctx.era == 4


def test_era_for_era_1_is_1(conn):
    ctx = compute_show_context(conn, show_date="1989-12-31", venue_id=None)
    assert ctx.era == 1


def test_era_for_era_2(conn):
    # 2.0 was 2002–2004
    ctx = compute_show_context(conn, show_date="2003-04-15", venue_id=None)
    assert ctx.era == 2


def test_era_for_era_3(conn):
    ctx = compute_show_context(conn, show_date="2015-07-01", venue_id=None)
    assert ctx.era == 3


def test_day_of_week_zero_is_monday(conn):
    # 2024-06-03 is a Monday.
    ctx = compute_show_context(conn, show_date="2024-06-03", venue_id=2)
    assert ctx.day_of_week == 0


def test_month_is_1_indexed(conn):
    ctx = compute_show_context(conn, show_date="2024-07-04", venue_id=1)
    assert ctx.month == 7


def test_tour_position_pulled_from_shows_table(conn):
    ctx = compute_show_context(conn, show_date="2024-06-03", venue_id=2)
    assert ctx.tour_position == 2
    ctx3 = compute_show_context(conn, show_date="2024-07-04", venue_id=1)
    assert ctx3.tour_position == 10


def test_tour_position_falls_back_to_one_when_unknown(conn):
    # Live show not yet ingested → tour_position absent.
    ctx = compute_show_context(conn, show_date="2030-01-01", venue_id=None)
    assert ctx.tour_position == 1
