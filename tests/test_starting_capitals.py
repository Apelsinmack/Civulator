"""E2E repro for issue #1: every player must actually get a capital on reset.

Pre-0.6, reset() called found_city() and ignored its return value. found_city
silently returns None when the start tile is Mountain/Ocean or within
min_city_distance of an already-placed capital — that player then started
city-less, was marked dead by end_turn on turn one, and their units were
deleted: the observed "city disappears near game start". The original fix
(v0.5.2) was a random-placement retry ladder.

design doc §6/D13, §11 P5: capitals now come from `MapData.starts`
(`mapgen/starts.py`) — fertility-scored, region-balanced, d_min-spaced, and
pre-validated settleable BEFORE `reset` ever calls `found_city`. There is no
retry loop left to regress: every player gets exactly one capital BY
CONSTRUCTION (a delivered start failing `found_city` would now raise
`StartPlacementError`, a contract violation, rather than silently retrying
or leaving a player city-less — see `GameEnvironment.reset`). These two
tests stay as the permanent regression/oracle pair for that guarantee.

map_type="basic" explicit (design doc §11 P3, still true post-P5: "same
starts stage" for both generators, design doc §4.1) at num_players=8 on
Standard's 24x48 — this is also the design doc §10/§11 P5 GATE's own
"Standard/8p max-density" oracle case (Standard's max_players).
"""

from civulator.game.environment import MIN_CITY_DISTANCE, GameEnvironment


def test_every_player_gets_exactly_one_capital():
    env = GameEnvironment(24, 48, num_players=8, map_type="basic")
    for seed in range(40):
        env.reset(seed=seed)
        for player in env.players:
            assert len(player.cities) == 1, (
                f"seed {seed}: {player.name} has {len(player.cities)} cities "
                f"— silent capital-placement failure (issue #1)"
            )


def test_capitals_respect_min_distance_and_terrain():
    env = GameEnvironment(24, 48, num_players=8, map_type="basic")
    for seed in range(10):
        env.reset(seed=seed)
        capitals = [p.cities[0].coordinates for p in env.players]
        for i, a in enumerate(capitals):
            tile = env.map.get_tile(a)
            # Settleable = land domain and not impassable (design doc §3)
            assert tile.domain == "land" and not tile.impassable
            for b in capitals[i + 1:]:
                assert env.map.distance_function(a, b) >= MIN_CITY_DISTANCE, (
                    f"seed {seed}: capitals {a} and {b} closer than min distance"
                )
