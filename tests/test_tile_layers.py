"""Tests for Tile.set_layers / TileLayers (design doc §3, §3.4, §11 P1).

set_layers is the only mutator for the new v0.6 composable layers. These
tests check: it validates (raises on an invalid `on` combination, without
mutating state), it composes and stores the result, it bumps
Map.terrain_epoch when given a map_ref, and — the part CAREFUL-flagged in the
task spec — it never touches the tile's existing legacy attributes
(terrain_type, features, resource, and the derived
defense_bonus/movement_cost/production_value), which keep driving all
gameplay unchanged until the P2a engine re-point.
"""

import pytest

from civulator import terrain_model as tm
from civulator.game.map import Map
from civulator.game.tile import Tile, TileLayers


class TestDefaultState:
    def test_fresh_tile_has_unset_layers(self):
        tile = Tile(0, 0, "Plains")
        assert tile.layers == TileLayers()
        assert tile.layers.base is None
        assert tile.composed is None


class TestSetLayersValid:
    def test_stores_layers(self):
        # Deer's Woods-branch has no base/relief restriction (§3.2), so this
        # exercises all four layers at once: base + relief + feature + resource.
        tile = Tile(0, 0, "Plains")
        tile.set_layers("Plains", relief="hills", feature="Woods", resource="Deer")
        assert tile.layers == TileLayers(
            base="Plains", relief="hills", feature="Woods", resource="Deer"
        )

    def test_computes_composed(self):
        tile = Tile(0, 0, "Plains")
        tile.set_layers("Grassland", relief="hills", feature="Woods")
        assert tile.composed == tm.compose("Grassland", relief="hills", feature="Woods")
        assert tile.composed.yields == (2, 2)
        assert tile.composed.movement == 3
        assert tile.composed.defense == 6

    def test_base_only(self):
        tile = Tile(0, 0, "Plains")
        tile.set_layers("Desert")
        assert tile.layers == TileLayers(base="Desert")
        assert tile.composed.domain == "land"

    def test_can_be_called_again_to_change_layers(self):
        tile = Tile(0, 0, "Plains")
        tile.set_layers("Grassland")
        tile.set_layers("Desert", relief="mountain")
        assert tile.layers.base == "Desert"
        assert tile.composed.impassable is True


class TestSetLayersInvalid:
    def test_raises_on_bad_on_constraint(self):
        tile = Tile(0, 0, "Plains")
        with pytest.raises(ValueError):
            tile.set_layers("Grassland", feature="Rainforest")

    def test_raises_on_unknown_name(self):
        tile = Tile(0, 0, "Plains")
        with pytest.raises(ValueError):
            tile.set_layers("NotATerrain")

    def test_failed_call_does_not_mutate_state(self):
        """validate() runs before any assignment — a rejected combo must leave
        layers/composed exactly as they were, not partially applied."""
        tile = Tile(0, 0, "Plains")
        tile.set_layers("Grassland", relief="hills", feature="Woods")
        layers_before = tile.layers
        composed_before = tile.composed

        with pytest.raises(ValueError):
            tile.set_layers("Grassland", feature="Rainforest")  # invalid: wrong base

        assert tile.layers == layers_before
        assert tile.composed == composed_before


class TestTerrainEpoch:
    def test_bumps_epoch_when_map_given(self):
        m = Map(4, 4)
        tile = Tile(0, 0, "Plains")
        assert m.terrain_epoch == 0
        tile.set_layers("Grassland", map_ref=m)
        assert m.terrain_epoch == 1
        tile.set_layers("Desert", map_ref=m)
        assert m.terrain_epoch == 2

    def test_no_bump_without_map_ref(self):
        tile = Tile(0, 0, "Plains")
        tile.set_layers("Grassland")  # no map_ref — must not raise, nothing to bump

    def test_no_bump_on_failed_validation(self):
        m = Map(4, 4)
        tile = Tile(0, 0, "Plains")
        with pytest.raises(ValueError):
            tile.set_layers("Grassland", feature="Rainforest", map_ref=m)
        assert m.terrain_epoch == 0

    def test_different_maps_have_independent_uids(self):
        m1 = Map(4, 4)
        m2 = Map(4, 4)
        assert m1.map_uid != m2.map_uid


class TestLegacyFieldsUntouched:
    def test_set_layers_does_not_change_terrain_type_or_legacy_state(self):
        tile = Tile(2, 3, "Grassland")
        tile.add_feature("Woods")
        tile.resource = "Iron"  # legacy resource — a distinct concept/value space

        legacy_snapshot = (
            tile.terrain_type,
            list(tile.features),
            tile.resource,
            tile.defense_bonus,
            tile.movement_cost,
            list(tile.production_value),
        )

        # A totally different combination in the new model — if this leaked
        # into legacy state, terrain_type/features/etc. would change.
        tile.set_layers("Desert", relief="mountain")

        assert (
            tile.terrain_type,
            list(tile.features),
            tile.resource,
            tile.defense_bonus,
            tile.movement_cost,
            list(tile.production_value),
        ) == legacy_snapshot

    def test_legacy_resource_and_features_lists_are_not_the_new_layers(self):
        tile = Tile(0, 0, "Plains")
        tile.set_layers("Plains", feature="Woods", resource="Deer")
        # Legacy attributes are a separate value space entirely.
        assert tile.resource is None
        assert tile.features == []
