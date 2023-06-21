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
    }
}
