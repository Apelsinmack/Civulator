"""E2E repro for issue #1: every player must actually get a capital on reset.

reset() called found_city() and ignored its return value. found_city silently
returns None when the start tile is Mountain/Ocean or within min_city_distance
of an already-placed capital — that player then starts city-less, is marked
dead by end_turn on turn one, and their units are deleted: the observed
"city disappears near game start".
"""

from civulator.game.environment import MIN_CITY_DISTANCE, GameEnvironment


def test_every_player_gets_exactly_one_capital():
    env = GameEnvironment(24, 48, num_players=8)
    for seed in range(40):
        env.reset(seed=seed)
        for player in env.players:
            assert len(player.cities) == 1, (
                f"seed {seed}: {player.name} has {len(player.cities)} cities "
                f"— silent capital-placement failure (issue #1)"
            )


def test_capitals_respect_min_distance_and_terrain():
    env = GameEnvironment(24, 48, num_players=8)
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
