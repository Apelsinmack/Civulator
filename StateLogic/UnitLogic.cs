using Data;
using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public class UnitLogic : IUnitLogic
    {
        private readonly ICityLogic? _cityLogic;
        private readonly World _world;
        private Unit _unit;

        public UnitLogic(World world, Unit unit)
        {
            _world = world;
            _unit = unit;
        }

        public UnitLogic(ICityLogic cityLogic, World world, Unit unit)
        {
            _cityLogic = cityLogic;
            _world = world;
            _unit = unit;
        }

        public void Disband()
        {
            _world.Map.Tiles[_unit.TileIndex].UnitIndexes.Remove(_unit.Index);
            _unit.Owner.UnitIndexes.Remove(_unit.Index);
            _world.Units.Remove(_unit.Index);
        }

        public void DisbandAllUnits(Player owner)
        {
            foreach (int index in owner.UnitIndexes.ToList())
            {
                Unit unit = _world.Units[index];
                _world.Map.Tiles[unit.TileIndex].UnitIndexes.Remove(index);
                unit.Owner.UnitIndexes.Remove(index);
                _world.Units.Remove(index);
            }
            owner.UnitIndexes.Clear(); //TODO: IS this needed?
        }

        public void Fortify()
        {
            _unit.MovementLeft = 0;
            _unit.Fortifying = true;
        }

        public void BuildCity()
        {
            if (_unit.Class == UnitType.Settler)
            {
                _cityLogic.GenerateCity(_unit.Owner, _world.Map.Tiles[_unit.TileIndex]);
                Disband();
            }
        }



        public static void ResetUnitMovements(World world, Player player)
        {
            foreach (int index in player.UnitIndexes)
            {
                world.Units[index].MovementLeft = Data.UnitClass.ByType[world.Units[index].Class].Movement;
            }
        }

        public static void MoveUnit(World world, int unitIndex, int tileIndex)
        {
            State.Unit unit = world.Units[unitIndex];
            world.Map.Tiles[unit.TileIndex].UnitIndexes.Remove(unitIndex);
            unit.MovementLeft--;
            unit.TileIndex = tileIndex;
            world.Map.Tiles[tileIndex].UnitIndexes.Add(unitIndex);
        }

        public static void FortifyUnits(World world, Player player)
        {
            foreach (int index in player.UnitIndexes)
            {
                if (world.Units[index].Fortifying)
                {
                    world.Units[index].Fortifying = false;
                    world.Units[index].Fortified = true;
                }
            }
        }

        public static Unit GenerateUnit(World world, UnitType unitClass, Player owner, int tileIndex)
        {
            int index = 0;
            if (world.Units.Count > 0)
            {
                index = world.Units.Max(unit => unit.Key) + 1;
            }
            Unit unit = new Unit(index, unitClass, owner, tileIndex, Data.UnitClass.ByType[unitClass].Movement);
            world.Units.Add(index, unit);
            world.Map.Tiles[tileIndex].UnitIndexes.Add(index);
            owner.UnitIndexes.Add(index);
            ExploreFromTile(world, owner, tileIndex, 1);

            return unit;
        }

        public static void ExploreFromTile(World world, Player player, int index, int sightRange = 1)
        {
            //TODO: Take in to account e.g. visibility range, terrain type of the index, terrain type of the surrounding area etc.
            player.ExploredTileIndexes.UnionWith(WorldLogic.GetAdjacentTileIndexes(world, index));
        }
    }
}
