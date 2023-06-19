using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    [Serializable]
    public class Map
    {
        public int MapBase { get; set; }
        public int MapHeight { get; set; }
        public Dictionary<int, Tile> Tiles { get; set; }

        public Map(int mapBase, int mapHeight, Dictionary<int, Tile> tiles)
        {
            MapBase = mapBase;
            MapHeight = mapHeight;
            Tiles = tiles;
        }
    }
}
