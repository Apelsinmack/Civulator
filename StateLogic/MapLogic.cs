using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public class MapLogic : IMapLogic
    {
        private readonly ITileLogic _tileLogic;

        public MapLogic(ITileLogic tileLogic)
        {
            _tileLogic = tileLogic;
        }

        public Map GenerateMap(int mapBase, int mapHeight)
        {
            Dictionary<int, Tile> tiles = new Dictionary<int, Tile>();

            for (int i = 0; i < mapBase * mapHeight; i++)
            {
                tiles.Add(i, _tileLogic.GenerateTile(i));
            }

            return new Map(mapBase, mapHeight, tiles);
        }
    }
}
