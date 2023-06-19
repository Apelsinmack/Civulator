using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State.Factories
{
    public class UnitFactory
    {
        public Unit GenerateUnit(UnitType unitType, Player player, Tile tile)
        {
            Unit unit = new Unit(unitType, player, tile.Index);
            tile.Units.Add(unit);

            return unit;
        }
    }
}
