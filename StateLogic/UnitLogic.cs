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

namespace StateLogic
{
    public static class UnitLogic
    {
        public static void ResetUnitMovements(World world, Player player)
        {
            foreach (int index in player.UnitIndexes)
            {
                world.Units[index].MovementLeft = Data.UnitClass.ByType[world.Units[index].Class].Movement;
            }
        }

        public static void RemoveUnit(World world, int index)
        {
            State.Unit unit = world.Units[index];
            world.Map.Tiles[unit.TileIndex].UnitIndexes.Remove(index);
            unit.Owner.UnitIndexes.Remove(index);
            world.Units.Remove(index);
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
            foreach (int index in player.UnitIndexes) {
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
            MapLogic.ExploreFromTile(world, owner, tileIndex, 1);

            return unit;
        }
    }
}
