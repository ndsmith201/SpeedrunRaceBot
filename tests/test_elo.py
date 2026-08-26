from pathlib import Path

from speedrun_race_bot.persistence import UserRepository
from speedrun_race_bot.race.elo import EloService


def test_adjustment_reverts_the_original_race_before_reapplying(tmp_path: Path) -> None:
    users = UserRepository(tmp_path / "users.sqlite3", Path("database/schema.sql"))
    elo = EloService(users)

    original = elo.apply({1: 1, 2: 2})
    corrected = elo.adjust(original, [2, 1])

    assert original == {1: 25, 2: -25}
    assert corrected == {2: 25, 1: -25}
    assert users.get_elo(1) == 1175
    assert users.get_elo(2) == 1225


def test_adjustment_requires_every_original_racer(tmp_path: Path) -> None:
    users = UserRepository(tmp_path / "users.sqlite3", Path("database/schema.sql"))
    elo = EloService(users)

    original = elo.apply({1: 1, 2: 2})

    try:
        elo.adjust(original, [1])
    except ValueError as error:
        assert "every original racer" in str(error)
    else:
        raise AssertionError("An incomplete replacement order should fail")
