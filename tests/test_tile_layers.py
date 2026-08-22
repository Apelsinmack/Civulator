"""Tests for Tile's terrain layers (design doc §3, §3.1, §3.4).

After the P2a re-point the layers ARE the tile's terrain state: there is no
`terrain_type` string, no feature list, and no separately stored
defense/movement/yield numbers — every gameplay property is composed from
`base_terrain x relief x feature x resource`, and `set_layers` is the only
mutator (validating, recomposing, bumping the map's terrain epoch).
"""

import pytest

from civulator import terrain_model as tm
from civulator.game.map import Map
from civulator.game.tile import Tile


class TestConstruction:
    def test_constructed_from_layers(self):
        tile = Tile(0, 0, "Plains", relief="hills", feature="Woods", resource="Deer")
        assert (tile.base_terrain, tile.relief, tile.feature, tile.resource) == (
            "Plains", "hills", "Woods", "Deer",
        )

    def test_relief_defaults_to_flat(self):
        tile = Tile(0, 0, "Grassland")
        assert tile.relief == "flat"
        assert tile.feature is None and tile.resource is None

    def test_composed_on_construction(self):
        tile = Tile(1, 2, "Grassland", relief="hills", feature="Woods")
        assert tile.composed == tm.compose("Grassland", relief="hills", feature="Woods")

    def test_invalid_combination_raises_at_construction(self):
        with pytest.raises(ValueError):
            Tile(0, 0, "Grassland", feature="Rainforest")


class TestSetLayers:
    def test_stores_layers(self):
        # Deer's Woods-branch has no base/relief restriction (§3.2), so this
        # exercises all four layers at once: base + relief + feature + resource.
        tile = Tile(0, 0, "Plains")
        tile.set_layers("Plains", relief="hills", feature="Woods", resource="Deer")
        assert (tile.base_terrain, tile.relief, tile.feature, tile.resource) == (
            "Plains", "hills", "Woods", "Deer",
        )

    def test_computes_composed(self):
        tile = Tile(0, 0, "Plains")
        tile.set_layers("Grassland", relief="hills", feature="Woods")
        assert tile.composed == tm.compose("Grassland", relief="hills", feature="Woods")
        assert tile.yields == (2, 2)
        assert tile.movement_cost == 3
        assert tile.defense_bonus == 6
        assert tile.los == (2, 1)

    def test_clears_layers_not_carried_over(self):
        tile = Tile(0, 0, "Plains", relief="hills", feature="Woods", resource="Deer")
        tile.set_layers("Desert")
        assert tile.relief == "flat"
        assert tile.feature is None
        assert tile.resource is None

    def test_can_be_called_again_to_change_layers(self):
        tile = Tile(0, 0, "Plains")
        tile.set_layers("Grassland")
        tile.set_layers("Desert", relief="mountain")
        assert tile.base_terrain == "Desert"
        assert tile.impassable is True


class TestSetLayersInvalid:
    def test_raises_on_bad_on_constraint(self):
        tile = Tile(0, 0, "Plains")
        with pytest.raises(ValueError):
            tile.set_layers("Grassland", feature="Rainforest")

    def test_raises_on_unknown_name(self):
        tile = Tile(0, 0, "Plains")
        with pytest.raises(ValueError):
            tile.set_layers("NotATerrain")

    def test_raises_on_relief_over_water(self):
        """Water is always flat (§3) — enforced by terrain_model.validate."""
        tile = Tile(0, 0, "Plains")
        with pytest.raises(ValueError):
            tile.set_layers("Ocean", relief="hills")

    def test_failed_call_does_not_mutate_state(self):
        """validate() runs before any assignment — a rejected combo must leave
        layers/composed exactly as they were, not partially applied."""
        tile = Tile(0, 0, "Plains")
        tile.set_layers("Grassland", relief="hills", feature="Woods")
        composed_before = tile.composed

        with pytest.raises(ValueError):
            tile.set_layers("Grassland", feature="Rainforest")  # invalid: wrong base

        assert tile.base_terrain == "Grassland"
        assert tile.relief == "hills"
        assert tile.feature == "Woods"
        assert tile.composed == composed_before


class TestComposedProperties:
    def test_domain_and_water(self):
        assert Tile(0, 0, "Grassland").domain == "land"
        assert Tile(0, 0, "Grassland").is_water() is False
        assert Tile(0, 0, "Coast").domain == "water"
        assert Tile(0, 0, "Coast").is_water() is True

    def test_is_passable_is_domain_relative(self):
        land = Tile(0, 0, "Plains")
        water = Tile(0, 0, "Lake")
        mountain = Tile(0, 0, "Plains", relief="mountain")

        assert land.is_passable("land") is True
        assert land.is_passable("water") is False
        assert water.is_passable("water") is True
        assert water.is_passable("land") is False
        assert mountain.is_passable("land") is False

    def test_label(self):
        assert Tile(0, 0, "Grassland").label == "Grassland"
        assert Tile(0, 0, "Grassland", relief="hills", feature="Woods").label == \
            "Grassland (Hills), Woods"
        assert Tile(0, 0, "Desert", relief="mountain").label == "Desert (Mountain)"

    def test_terrain_type_is_the_deprecated_label_alias(self):
        """Read-only alias kept only for the not-yet-updated visual tools (P2b)."""
        tile = Tile(0, 0, "Grassland", relief="hills")
        assert tile.terrain_type == tile.label
        with pytest.raises(AttributeError):
            tile.terrain_type = "Hills"

    def test_no_river_state_on_the_tile(self):
        """Rivers are Map edges only (§9.1) — has_river is gone."""
        assert not hasattr(Tile(0, 0, "Plains"), "has_river")


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
