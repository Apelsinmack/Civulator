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

        public static IEnumerable<Tile> GetAdjacentTiles(Map map, int index)
        {
            return map.Tiles.Where(tile => GetAdjacentTileIndexes(map.MapBase, index).Contains(tile.Key)).Select(tile => tile.Value);
        }

        public static void ExploreFromTile(World world, Player player, int index, int sightRange = 1) {
            //TODO: Take in to account e.g. visibility range, terrain type of the index, terrain type of the surrounding area etc.
            player.ExploredTileIndexes.UnionWith(GetAdjacentTileIndexes(world.Map.MapBase, index));
        }
    }
}
