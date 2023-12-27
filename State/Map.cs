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
        public int MapWidth { get; set; }
        public int MapHeight { get; set; }
        public Dictionary<int, Tile> Tiles { get; set; }

        public Map(int mapWidth, int mapHeight, Dictionary<int, Tile> tiles)
        {
            MapWidth = mapWidth;
            MapHeight = mapHeight;
            Tiles = tiles;
        }
    }
}
