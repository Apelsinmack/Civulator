"""Property test for issue #42: vectorized mask building must stay bit-identical.

Profiling (#34) found mask building was 8.31% of training wall-clock, the
#1 engine-side hotspot, because of two things:
  1. get_valid_select_mask / get_valid_moves_mask allocated a fresh CUDA
     tensor and wrote individual scalar entries into it in a Python loop.
  2. horizontal_wrap_padding hand-looped what F.pad(mode='circular') does
     natively.

The fix (civulator/agents/networks.py) changes *how* these masks are built,
not what they mean. This test keeps a private, verbatim copy of the
pre-#42 implementations (`_reference_*` below) and asserts, over many
random game states, that the real (post-#42) functions produce bit-identical
output to the reference — same values, dtype, shape, and device semantics.

Do NOT "fix" the _reference_* functions to match new behavior — if a real
regression makes them disagree, that's the test doing its job.
"""

import random

import numpy as np
import pytest
import torch
import torch.nn.functional as F

from civulator.agents.networks import (
    get_valid_moves_mask,
    get_valid_select_mask,
    horizontal_wrap_padding,
)
from civulator.agents.state_encoders import EnhancedStateEncoder
from civulator.game.environment import GameEnvironment
from civulator.mapgen.starts import StartPlacementError
from civulator.game.unit import (
    NUM_UNIT_SLOTS,
    ArcherUnit,
    CatapultUnit,
    HorsemanUnit,
    SettlerUnit,
    SpearmanUnit,
    SwordsmanUnit,
    WarriorUnit,
    WorkerUnit,
)

from test_combat_range import make_flat_env, place

DEVICES = ["cpu"] + (["cuda"] if torch.cuda.is_available() else [])


# ---------------------------------------------------------------------------
# Reference implementations — verbatim copies of the pre-#42 code that lived
# in civulator/agents/networks.py. Copied, not imported, so this test keeps
# meaning after the real functions are rewritten.
# ---------------------------------------------------------------------------


def _reference_horizontal_wrap_padding(state, padding_size=1):
    """Verbatim copy of the original horizontal_wrap_padding (pre-#42)."""
    if len(state.shape) == 4:
        batch_size, d, n, m = state.shape
        device = state.device

        padded = torch.zeros(
            batch_size, d, n + padding_size * 2, m + padding_size * 2, device=device
        )

        padded[:, :, padding_size : n + padding_size, padding_size : m + padding_size] = state

        for i in range(padding_size):
            padded[:, :, padding_size : n + padding_size, i] = state[:, :, :, m - (padding_size - i)]
            padded[:, :, padding_size : n + padding_size, m + padding_size + i] = state[:, :, :, i]

    else:
        d, n, m = state.shape
        device = state.device

        padded = torch.zeros(d, n + padding_size * 2, m + padding_size * 2, device=device)

        padded[:, padding_size : n + padding_size, padding_size : m + padding_size] = state

        for i in range(padding_size):
            padded[:, padding_size : n + padding_size, i] = state[:, :, m - (padding_size - i)]
            padded[:, padding_size : n + padding_size, m + padding_size + i] = state[:, :, i]

    return padded


def _reference_get_valid_select_mask(state, game_env):
    """Verbatim copy of the original get_valid_select_mask (pre-#42)."""
    n, m = state.shape[1], state.shape[2]
    device = state.device

    mask = torch.zeros(n * m * NUM_UNIT_SLOTS, device=device)
    current_player = game_env.current_player
    for unit in current_player.units:
        if unit.health > 0 and unit.movement_points > 0:
            r, c = unit.coordinates
            tile_idx = r * m + c
            mask[tile_idx * NUM_UNIT_SLOTS + unit.slot] = 1.0
    return mask


def _reference_get_valid_moves_mask(state, selected_pos, game_env):
    """Verbatim copy of the original get_valid_moves_mask (pre-#42)."""
    _, n, m = state.shape
    device = state.device

    tile_pos = selected_pos // NUM_UNIT_SLOTS
    selected_slot = selected_pos % NUM_UNIT_SLOTS

    if tile_pos >= n * m:
        return torch.zeros(n * m, device=device)

    row = tile_pos // m
    col = tile_pos % m

    valid_move_mask = torch.zeros(n, m, device=device)

    selected_unit = game_env.get_unit_in_slot(
        (row, col), selected_slot, game_env.current_player
    )
    if selected_unit is None or selected_unit.movement_points <= 0:
        return valid_move_mask.flatten()

    from civulator.game.map import HEX_DIRECTIONS
    for dr, dc in HEX_DIRECTIONS:
        new_row = row + dr
        new_col = (col + dc) % m
        if new_row < 0 or new_row >= n:
            continue

        if not selected_unit.can_enter(game_env.map.get_tile((new_row, new_col))):
            continue

        friendly_in_slot = game_env.is_slot_occupied(
            (new_row, new_col), selected_unit.slot, game_env.current_player
        )
        if not friendly_in_slot:
            valid_move_mask[new_row, new_col] = 1
        else:
            enemy_there = any(
                u.player != game_env.current_player
                for u in game_env.get_units_at((new_row, new_col))
            )
            if enemy_there:
                valid_move_mask[new_row, new_col] = 1

    if selected_unit.get_base_ranged_strength() > 0:
        attack_range = selected_unit.get_range()
        for player in game_env.players:
            if player is game_env.current_player:
                continue
            for enemy in player.units:
                er, ec = enemy.coordinates
                if (
                    game_env.map.distance_function((row, col), (er, ec)) <= attack_range
                    and game_env.check_line_of_sight((row, col), (er, ec))
                ):
                    valid_move_mask[er, ec] = 1

    valid_move_mask[row, col] = 1

    return valid_move_mask.flatten()


# ---------------------------------------------------------------------------
# horizontal_wrap_padding: random tensors, both 3D (unbatched) and 4D
# (batched), padding_size 1 (the live default, kernel_size=3) and 2.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("device", DEVICES)
def test_horizontal_wrap_padding_matches_reference(device):
    torch.manual_seed(1234)
    shapes = [
        (3, 4, 5),          # unbatched, small
        (7, 6, 9),          # unbatched, wider
        (2, 3, 4, 5),       # batched
        (4, 27, 8, 16),     # batched, fog-of-war depth, engine map size
        (1, 5, 6, 6),       # batch of 1, square
    ]
    for shape in shapes:
        for padding_size in (1, 2):
            state = torch.randn(*shape, device=device)
            expected = _reference_horizontal_wrap_padding(state, padding_size)
            actual = horizontal_wrap_padding(state, padding_size)
            assert torch.equal(expected, actual), f"mismatch for shape={shape}, padding={padding_size}"
            assert expected.dtype == actual.dtype
            assert expected.shape == actual.shape
            assert expected.device == actual.device


# ---------------------------------------------------------------------------
# Random game-state generation for get_valid_select_mask / get_valid_moves_mask.
# ---------------------------------------------------------------------------

MILITARY_UNIT_CLASSES = [WarriorUnit, ArcherUnit, SwordsmanUnit, SpearmanUnit, HorsemanUnit, CatapultUnit]
CIVILIAN_UNIT_CLASSES = [SettlerUnit, WorkerUnit]


def _build_random_scenario(rng, n, m, num_players):
    """A GameEnvironment with random terrain, unit placements, and edge cases.

    Includes: units at column 0 and m-1 (map-seam wrap), fortified units,
    stacked slots (military + civilian on the same tile), dead units,
    already-moved units, ranged units near/beyond range with LoS blockers,
    and (sometimes) a founded city.
    """
    # Start placement (region/fertility based) can occasionally fail to find
    # a legal start on small maps with several players -- irrelevant to this
    # test since every tile is repainted right below, so just retry with a
    # different seed rather than let generation flakiness fail a mask test.
    env = None
    for attempt in range(10):
        try:
            env = GameEnvironment(
                n, m, num_players=num_players, map_type="basic",
                seed=rng.randrange(1 << 30) + attempt,
            )
            break
        except StartPlacementError:
            continue
    if env is None:
        # Safe fallback: bigger board, fewer players -- should always place.
        env = GameEnvironment(10, 20, num_players=2, map_type="basic", seed=rng.randrange(1 << 30))
        n, m, num_players = 10, 20, 2

    # Terrain: mostly Plains, with some impassable mountain and some water
    # scattered in so can_enter's terrain-domain check gets real variety.
    for r in range(n):
        for c in range(m):
            roll = rng.random()
            if roll < 0.08:
                env.map.tiles[r, c].set_layers("Ocean", map_ref=env.map)
            elif roll < 0.18:
                env.map.tiles[r, c].set_layers("Plains", relief="mountain", map_ref=env.map)
            else:
                env.map.tiles[r, c].set_layers("Plains", map_ref=env.map)

    occupied_slots = set()  # (player_idx, r, c, slot)

    def try_place(player_idx, cls, r, c):
        # Determine the slot this class would occupy without instantiating twice.
        probe = cls(env.players[player_idx], (r, c))
        key = (player_idx, r, c, probe.slot)
        if key in occupied_slots:
            return None
        occupied_slots.add(key)
        return place(env, cls, player_idx, (r, c))

    units = []
    for p in range(num_players):
        for _ in range(rng.randint(2, 5)):
            # Bias toward the map seam (col 0 / m-1) so wrap adjacency is
            # exercised, but also place elsewhere.
            c = rng.choice([0, m - 1, rng.randrange(m), rng.randrange(m)])
            r = rng.randrange(n)
            cls = rng.choice(MILITARY_UNIT_CLASSES)
            unit = try_place(p, cls, r, c)
            if unit is None:
                continue
            if rng.random() < 0.15:
                unit.health = 0.0  # dead: must be excluded from select mask
            elif rng.random() < 0.2:
                unit.movement_points = 0  # already acted this turn
            elif rng.random() < 0.15:
                unit.fortify()  # sets movement_points = 0, fortification = 1
            units.append(unit)

        # Civilian in the same slot family as above, sometimes stacked with
        # a military unit already on that tile (different slot -> legal).
        if rng.random() < 0.7 and units:
            base = rng.choice([u for u in units if u.player is env.players[p]] or units)
            r, c = base.coordinates if rng.random() < 0.5 else (rng.randrange(n), rng.randrange(m))
            cls = rng.choice(CIVILIAN_UNIT_CLASSES)
            unit = try_place(p, cls, r, c)
            if unit is not None:
                units.append(unit)

    # Occasionally found a city (may silently fail if the spot is invalid --
    # that's fine, masks don't care about cities either way).
    if rng.random() < 0.3 and units:
        r, c = rng.randrange(n), rng.randrange(m)
        env.found_city(env.players[0], (r, c), "TestCity")

    cp_idx = rng.randrange(num_players)
    env.current_player_index = cp_idx
    env.current_player = env.players[cp_idx]

    return env, units, cp_idx


def _selected_pos_candidates(rng, env, units, n, m):
    """A handful of selected_pos values to probe get_valid_moves_mask with,
    including out-of-range and empty-slot edge cases."""
    candidates = []
    for unit in units:
        r, c = unit.coordinates
        candidates.append((r * m + c) * NUM_UNIT_SLOTS + unit.slot)

    # Explicit seam tiles regardless of whether a unit happens to be there.
    for r in (0, n - 1):
        for c in (0, m - 1):
            for slot in range(NUM_UNIT_SLOTS):
                candidates.append((r * m + c) * NUM_UNIT_SLOTS + slot)

    # Out-of-range tile_pos.
    candidates.append(n * m * NUM_UNIT_SLOTS + rng.randrange(NUM_UNIT_SLOTS))

    # A handful of purely random tile-slot combos (often an empty slot).
    for _ in range(5):
        r, c = rng.randrange(n), rng.randrange(m)
        slot = rng.randrange(NUM_UNIT_SLOTS)
        candidates.append((r * m + c) * NUM_UNIT_SLOTS + slot)

    return candidates


N_SCENARIOS = 55


def _scenario_params(seed):
    rng = random.Random(seed)
    n = rng.choice([6, 8, 10])
    m = rng.choice([8, 12, 16])
    num_players = rng.choice([2, 3, 4])
    fog = rng.random() < 0.5
    return n, m, num_players, fog


@pytest.mark.parametrize("device", DEVICES)
def test_select_and_move_masks_match_reference_over_random_states(device):
    torch_device = torch.device(device)

    for seed in range(N_SCENARIOS):
        rng = random.Random(seed)
        n, m, num_players, fog = _scenario_params(seed)
        env, units, cp_idx = _build_random_scenario(rng, n, m, num_players)
        # _build_random_scenario may fall back to a different size if start
        # placement kept failing on the requested one -- use what actually got built.
        n, m = env.n, env.m

        if fog:
            env.update_exploration(cp_idx)
        encoder = EnhancedStateEncoder(fog_of_war=fog)
        state = encoder.encode(env, cp_idx, device=torch_device)

        # --- select mask ---
        expected_select = _reference_get_valid_select_mask(state, env)
        actual_select = get_valid_select_mask(state, env)

        assert torch.equal(expected_select, actual_select), f"select mask mismatch, seed={seed}"
        assert expected_select.dtype == actual_select.dtype
        assert expected_select.shape == actual_select.shape
        assert expected_select.device == actual_select.device

        # --- move mask, many selected_pos values per scenario ---
        for selected_pos in _selected_pos_candidates(rng, env, units, n, m):
            expected_moves = _reference_get_valid_moves_mask(state, selected_pos, env)
            actual_moves = get_valid_moves_mask(state, selected_pos, env)

            assert torch.equal(expected_moves, actual_moves), (
                f"move mask mismatch, seed={seed}, selected_pos={selected_pos}"
            )
            assert expected_moves.dtype == actual_moves.dtype
            assert expected_moves.shape == actual_moves.shape
            assert expected_moves.device == actual_moves.device


def test_select_mask_excludes_dead_and_spent_units_smoke():
    """Small, deterministic sanity check on top of the randomized sweep above."""
    env = make_flat_env()
    alive = place(env, WarriorUnit, 0, (2, 2))
    dead = place(env, WarriorUnit, 0, (3, 3))
    dead.health = 0.0
    spent = place(env, WarriorUnit, 0, (4, 4))
    spent.movement_points = 0

    state = EnhancedStateEncoder(fog_of_war=False).encode(env, 0)
    mask = get_valid_select_mask(state, env)
    ref = _reference_get_valid_select_mask(state, env)
    assert torch.equal(mask, ref)

    m = env.m
    assert mask[(2 * m + 2) * NUM_UNIT_SLOTS + alive.slot] == 1.0
    assert mask[(3 * m + 3) * NUM_UNIT_SLOTS + dead.slot] == 0.0
    assert mask[(4 * m + 4) * NUM_UNIT_SLOTS + spent.slot] == 0.0


def test_move_mask_wraps_across_seam_smoke():
    """Small, deterministic sanity check: seam wrap (col 0 <-> col m-1)."""
    env = make_flat_env()
    warrior = place(env, WarriorUnit, 0, (3, 0))
    place(env, ArcherUnit, 1, (3, env.m - 1))  # adjacent across the seam

    state = EnhancedStateEncoder(fog_of_war=False).encode(env, 0)
    selected_pos = (3 * env.m + 0) * NUM_UNIT_SLOTS + warrior.slot
    mask = get_valid_moves_mask(state, selected_pos, env)
    ref = _reference_get_valid_moves_mask(state, selected_pos, env)
    assert torch.equal(mask, ref)
    assert mask.reshape(env.n, env.m)[3, env.m - 1] == 1.0
