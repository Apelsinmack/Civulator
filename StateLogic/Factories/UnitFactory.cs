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
        public Unit GenerateUnit(UnitType unitType, Player player, Tile tile, int mapBase)
        {
            Unit unit = new Unit(unitType, player, tile.Index);
            tile.Units.Add(unit);
            player.DiscoveredTileIndexes.UnionWith(MapLogic.GetAdjacentTileIndexes(mapBase, tile.Index));

            return unit;
        }
    }
}
