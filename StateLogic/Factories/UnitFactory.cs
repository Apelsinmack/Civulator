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
        public Unit GenerateUnit(Map map, UnitClassType unitClass, Player owner, Tile tile)
        {
            Unit unit = new Unit(unitClass, owner, tile.Index);
            tile.Units.Add(unit);
            MapLogic.ExploreFromTile(owner, map, tile.Index, 1);

            return unit;
        }
    }
}
