using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic
{
    public static class UnitLogic
    {
        public static IEnumerable<Unit> GetPlayerUnits(World world, Player player)
        {
            return world.Map.Tiles.SelectMany(tile => tile.Value.Units).Where(unit => unit.Owner.Id == player.Id);
        }

        public static void ResetUnitMovements(World world, Player player)
        {
            IEnumerable<Unit> units = GetPlayerUnits(world, player);
            foreach (Unit unit in units)
            {
                unit.MovementLeft = Data.UnitClass.ByType[unit.Class].Movement;
            }
        }

        public static void RemoveUnit(World world, int tileIndex, Guid unitId)
        {
            world.Map.Tiles[tileIndex].Units.RemoveAll(unit => unit.Id == unitId);
        }

        public static void MoveUnit(World world, Unit unit, int tileIndex)
        {
            unit.MovementLeft--;
            UnitLogic.RemoveUnit(world, unit.TileIndex, unit.Id);
            unit.TileIndex = tileIndex;;
            world.Map.Tiles[tileIndex].Units.Add(unit);
        }

        public static void FortifyUnits(World world, Player player)
        {
            foreach (var unit in GetPlayerUnits(world, player).Where(unit => unit.Fortifying))
            {
                unit.Fortifying = false;
                unit.Fortified = true;
            }
        }
    }
}
