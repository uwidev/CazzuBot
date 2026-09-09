"""core.utils.top_percent — the "top X%" band shown on the cards."""

from core.utils import top_percent


def test_leader_is_top_one_percent() -> None:
    assert top_percent(1, 341) == 1


def test_band_rounds_up_so_it_never_overclaims() -> None:
    # 1% of 341 is 3.41 members, so rank 4 is inside the top 2%, not 1%
    assert top_percent(4, 341) == 2
    assert top_percent(3, 341) == 1


def test_last_place_is_the_whole_board() -> None:
    assert top_percent(341, 341) == 100
    assert top_percent(10, 10) == 100


def test_empty_board_does_not_divide_by_zero() -> None:
    assert top_percent(1, 0) == 100
    assert top_percent(0, 0) == 100
