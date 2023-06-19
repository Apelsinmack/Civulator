using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic
{
    public static class MapLogic
    {
        public static List<int> GetAdjacentTileIndexes(int mapBase, int index)
        {
            List<int> indexes = new()
            {
                index - mapBase, // ↑
                index + mapBase // ↓
            };
            if (index % mapBase % 2 == 0)
            {
                indexes.Add(index - mapBase + 1); // ↗
                indexes.Add(index + 1); // ↘
                indexes.Add(index - 1); // ↙
                indexes.Add(index - 1 - mapBase); // ↖
            }
            else
            {
                indexes.Add(index + 1); // ↗
                indexes.Add(index + 1 + mapBase); // ↘
                indexes.Add(index - 1 + mapBase); // ↙
                indexes.Add(index - 1); // ↖
            }
            return indexes;
        }

        public static List<Tile> GetAdjacentTiles(Map map, int index)
        {
            return map.Tiles.Where(tile => GetAdjacentTileIndexes(map.MapBase, index).Contains(tile.Key)).Select(tile => tile.Value).ToList();
        }
    }
}
