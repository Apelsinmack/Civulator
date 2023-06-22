using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic.Factories
{
    public class UnitFactory
    {
        public Unit GenerateUnit(World world, UnitClassType unitClass, Player owner, Tile tile)
        {
            int index = 0;
            if (world.Units.Count > 0)
            {
                index = world.Units.Max(unit => unit.Key) + 1;
            }
            Unit unit = new Unit(index, unitClass, owner, tile.Index, Data.UnitClass.ByType[unitClass].Movement);
            world.Units.Add(index, unit);
            tile.UnitIndexes.Add(index);
            owner.UnitIndexes.Add(index);
            MapLogic.ExploreFromTile(world, owner, tile.Index, 1);

            return unit;
        }
    }
}
