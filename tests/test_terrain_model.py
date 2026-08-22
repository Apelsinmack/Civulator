"""Tests for civulator.terrain_model (design doc §3.1, §11 P1).

Covers: additive composition and yield clamping, the impassable flag (relief
mountain only, D6), domain, and the `on` placement matrix (check_on +
validate) — including Deer's "Woods or Tundra" disjunction, which needs the
list-of-mappings extension documented in terrain_model.py's module docstring.
"""

import pytest

from civulator import terrain_model as tm


class TestComposeAdditivity:
    def test_grassland_hills_woods(self):
        """The worked example from design doc §3.1 / the P1 task spec."""
        c = tm.compose("Grassland", relief="hills", feature="Woods")
        assert c.movement == 3
        assert c.defense == 6
        assert c.yields == (2, 2)

    def test_base_only_matches_config(self):
        c = tm.compose("Grassland")
        assert c.yields == (2, 0)
        assert c.movement == 1
        assert c.defense == 0
        assert c.los == (0, 0)
        assert c.domain == "land"

    def test_relief_none_equals_relief_flat(self):
        """Omitting relief and explicitly passing 'flat' must compose identically
        (flat's contribution is all-zero; set_layers(relief=None) means flat)."""
        assert tm.compose("Grassland", feature="Woods") == tm.compose(
            "Grassland", relief="flat", feature="Woods"
        )

    def test_resource_adds_on_top_of_feature(self):
        # Grassland(2,0) + hills(0,1) + Stone resource(0,1)
        c = tm.compose("Grassland", relief="hills", resource="Stone")
        assert c.yields == (2, 2)

    def test_los_is_additive(self):
        # Grassland(0,0) + hills(1,1) + Woods(1,0)
        c = tm.compose("Grassland", relief="hills", feature="Woods")
        assert c.los == (2, 1)

    def test_defense_has_no_cap_and_can_go_negative(self):
        # Grassland(0) + Marsh(-2) — D6: "defense: additive, no cap"
        c = tm.compose("Grassland", feature="Marsh")
        assert c.defense == -2

    def test_yields_clamp_at_zero(self, monkeypatch):
        """D6: yields are additive, clamped >= 0. Real 0.6 content never drives
        a total negative, so the clamp is exercised here via a synthetic layer
        (auto-reverted by monkeypatch) rather than relying on game-balance
        numbers that may be retuned later."""
        monkeypatch.setitem(tm.FEATURE_TABLE, "_TestNegative", {"yields": [-10, -10]})
        c = tm.compose("Desert", feature="_TestNegative")  # Desert yields = (0, 0)
        assert c.yields == (0, 0)


class TestImpassableAndDomain:
    def test_mountain_is_impassable(self):
        assert tm.compose("Desert", relief="mountain").impassable is True

    def test_flat_and_hills_are_not_impassable(self):
        assert tm.compose("Grassland").impassable is False
        assert tm.compose("Grassland", relief="hills").impassable is False

    def test_impassable_only_from_relief_not_feature_or_resource(self):
        # No feature/resource in the P1 schema sets impassable; confirm the
        # flag tracks relief alone regardless of what else is on the tile.
        c = tm.compose("Plains", relief="flat", feature="Woods")
        assert c.impassable is False

    def test_land_domain(self):
        assert tm.compose("Grassland").domain == "land"
        assert tm.compose("Desert", relief="mountain").domain == "land"

    def test_water_domain(self):
        assert tm.compose("Coast").domain == "water"
        assert tm.compose("Lake").domain == "water"
        assert tm.compose("Ocean").domain == "water"


class TestOnMatrixFeatures:
    """The exact valid/invalid cases named in the P1 task spec."""

    def test_woods_on_grassland_flat_is_valid(self):
        assert tm.check_on("feature", "Woods", "Grassland", "flat", None) is True
        tm.validate("Grassland", relief="flat", feature="Woods")  # must not raise

    def test_rainforest_on_grassland_is_invalid(self):
        assert tm.check_on("feature", "Rainforest", "Grassland", "flat", None) is False
        with pytest.raises(ValueError):
            tm.validate("Grassland", relief="flat", feature="Rainforest")

    def test_marsh_on_hills_is_invalid(self):
        assert tm.check_on("feature", "Marsh", "Grassland", "hills", None) is False
        with pytest.raises(ValueError):
            tm.validate("Grassland", relief="hills", feature="Marsh")

    def test_woods_on_desert_is_invalid(self):
        assert tm.check_on("feature", "Woods", "Desert", "flat", None) is False
        with pytest.raises(ValueError):
            tm.validate("Desert", relief="flat", feature="Woods")

    @pytest.mark.parametrize(
        "base,relief",
        [("Plains", "flat"), ("Plains", "hills"), ("Grassland", "flat"), ("Tundra", "hills")],
    )
    def test_woods_valid_bases_and_relief(self, base, relief):
        tm.validate(base, relief=relief, feature="Woods")

    def test_rainforest_only_on_plains(self):
        tm.validate("Plains", relief="flat", feature="Rainforest")
        with pytest.raises(ValueError):
            tm.validate("Tundra", relief="flat", feature="Rainforest")

    def test_reef_only_on_coast(self):
        tm.validate("Coast", feature="Reef")
        with pytest.raises(ValueError):
            tm.validate("Lake", feature="Reef")

    def test_ice_on_coast_or_ocean(self):
        tm.validate("Coast", feature="Ice")
        tm.validate("Ocean", feature="Ice")
        with pytest.raises(ValueError):
            tm.validate("Lake", feature="Ice")


class TestOnMatrixResources:
    def test_wheat_on_flat_plains(self):
        tm.validate("Plains", relief="flat", resource="Wheat")

    def test_wheat_on_hills_plains_is_invalid(self):
        with pytest.raises(ValueError):
            tm.validate("Plains", relief="hills", resource="Wheat")

    def test_wheat_on_desert_floodplains(self):
        """P1 found the single-mapping form of Wheat's `on` unsatisfiable on its
        Floodplains branch (Floodplains exist only on Desert, but the mapping
        also demanded a Plains base). P2a fixed it to the Civ-6-faithful
        disjunction: flat Plains, OR Desert Floodplains."""
        tm.validate("Desert", relief="flat", feature="Floodplains", resource="Wheat")
        with pytest.raises(ValueError):
            tm.validate("Plains", relief="flat", feature="Woods", resource="Wheat")

    def test_rice_allows_marsh(self):
        tm.validate("Grassland", relief="flat", resource="Rice")
        tm.validate("Grassland", relief="flat", feature="Marsh", resource="Rice")

    def test_cattle_rejects_any_feature(self):
        tm.validate("Grassland", relief="flat", resource="Cattle")
        with pytest.raises(ValueError):
            tm.validate("Grassland", relief="flat", feature="Marsh", resource="Cattle")

    def test_sheep_on_hills_any_land_base(self):
        tm.validate("Grassland", relief="hills", resource="Sheep")
        tm.validate("Tundra", relief="hills", resource="Sheep")
        with pytest.raises(ValueError):
            tm.validate("Grassland", relief="flat", resource="Sheep")

    def test_stone_on_grassland_flat_or_hills(self):
        tm.validate("Grassland", relief="flat", resource="Stone")
        tm.validate("Grassland", relief="hills", resource="Stone")
        with pytest.raises(ValueError):
            tm.validate("Plains", relief="flat", resource="Stone")

    def test_deer_on_woods_any_base(self):
        """'Woods or Tundra' (§3.2) — the Woods branch: any base with the
        Woods feature, not just Tundra."""
        tm.validate("Plains", relief="flat", feature="Woods", resource="Deer")
        tm.validate("Grassland", relief="flat", feature="Woods", resource="Deer")
        tm.validate("Tundra", relief="flat", feature="Woods", resource="Deer")

    def test_deer_on_bare_tundra(self):
        """'Woods or Tundra' — the Tundra branch: valid with no feature at all."""
        tm.validate("Tundra", relief="flat", resource="Deer")
        tm.validate("Tundra", relief="hills", resource="Deer")

    def test_deer_rejects_bare_non_tundra(self):
        with pytest.raises(ValueError):
            tm.validate("Plains", relief="flat", resource="Deer")

    def test_bananas_on_rainforest(self):
        tm.validate("Plains", relief="flat", feature="Rainforest", resource="Bananas")
        with pytest.raises(ValueError):
            tm.validate("Plains", relief="flat", resource="Bananas")

    def test_fish_on_coast_or_lake_not_ocean(self):
        tm.validate("Coast", resource="Fish")
        tm.validate("Lake", resource="Fish")
        with pytest.raises(ValueError):
            tm.validate("Ocean", resource="Fish")


class TestWaterIsAlwaysFlat:
    """§3: relief is land-only — validate rejects it on a water-domain base."""

    @pytest.mark.parametrize("base", ["Coast", "Lake", "Ocean"])
    @pytest.mark.parametrize("relief", ["hills", "mountain"])
    def test_relief_on_water_is_invalid(self, base, relief):
        with pytest.raises(ValueError):
            tm.validate(base, relief=relief)

    @pytest.mark.parametrize("base", ["Coast", "Lake", "Ocean"])
    def test_flat_water_is_valid(self, base):
        tm.validate(base, relief="flat")


class TestCanEnter:
    """The canonical terrain-domain passability check (§3.3, D8)."""

    def test_land_unit_on_land(self):
        assert tm.can_enter("land", tm.compose("Plains")) is True

    def test_land_unit_on_water(self):
        assert tm.can_enter("land", tm.compose("Coast")) is False

    def test_water_unit_on_water(self):
        assert tm.can_enter("water", tm.compose("Ocean")) is True

    def test_mountain_blocks_everyone(self):
        assert tm.can_enter("land", tm.compose("Plains", relief="mountain")) is False

    def test_missing_tile_admits_nobody(self):
        assert tm.can_enter("land", None) is False


class TestValidateCatchesUnknownNames:
    def test_unknown_base(self):
        with pytest.raises(ValueError):
            tm.validate("Volcano")

    def test_unknown_relief(self):
        with pytest.raises(ValueError):
            tm.validate("Grassland", relief="cliff")

    def test_unknown_feature(self):
        with pytest.raises(ValueError):
            tm.validate("Grassland", feature="Jungle")

    def test_unknown_resource(self):
        with pytest.raises(ValueError):
            tm.validate("Grassland", resource="Gold")


class TestSchemaContent:
    """Sanity checks on the config content itself (P1 deliverable 4)."""

    def test_eight_base_terrains(self):
        assert set(tm.BASE_TABLE.keys()) == {
            "Grassland", "Plains", "Desert", "Tundra", "Snow", "Coast", "Lake", "Ocean",
        }

    def test_three_relief_values(self):
        assert set(tm.RELIEF_TABLE.keys()) == {"flat", "hills", "mountain"}

    def test_seven_features(self):
        assert set(tm.FEATURE_TABLE.keys()) == {
            "Woods", "Rainforest", "Marsh", "Floodplains", "Oasis", "Reef", "Ice",
        }

    def test_eight_resources_all_bonus_class(self):
        assert set(tm.RESOURCE_TABLE.keys()) == {
            "Wheat", "Rice", "Cattle", "Sheep", "Stone", "Deer", "Bananas", "Fish",
        }
        for name, entry in tm.RESOURCE_TABLE.items():
            assert entry.get("class") == "bonus", name

    def test_river_crossing_cost(self):
        from civulator.config import CFG

        assert CFG["terrain"]["river"]["crossing_cost"] == 1
