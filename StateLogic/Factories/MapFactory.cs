using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic.Factories
{
    public class MapFactory
    {
        public Map GenerateMap(int mapBase, int mapHeight)
        {
            TileFactory tileFactory = new TileFactory();
            Dictionary<int, Tile> tiles = new Dictionary<int, Tile>();

            for (int i = 0; i < mapBase * mapHeight; i++)
            {
                tiles.Add(i, tileFactory.GenerateTile(i));
            }

            return new Map(mapBase, mapHeight, tiles);
        }

        internal IEnumerable<object> GetAdjacentTiles(Map map, int randomIndex)
        {
            throw new NotImplementedException();
        }
    }
}
