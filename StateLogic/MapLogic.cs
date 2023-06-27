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
        public static Map GenerateMap(int mapBase, int mapHeight)
        {
            Dictionary<int, Tile> tiles = new Dictionary<int, Tile>();

            for (int i = 0; i < mapBase * mapHeight; i++)
            {
                tiles.Add(i, TileLogic.GenerateTile(i));
            }

            return new Map(mapBase, mapHeight, tiles);
        }

        public static List<int> GetAdjacentTileIndexes(World world, int index)
        {
            List<int> indexes = new()
            {
                index - world.Map.MapBase, // ↑
                index + world.Map.MapBase // ↓
            };
            if (index % world.Map.MapBase % 2 == 0)
            {
                indexes.Add(index - world.Map.MapBase + 1); // ↗
                indexes.Add(index + 1); // ↘
                indexes.Add(index - 1); // ↙
                indexes.Add(index - 1 - world.Map.MapBase); // ↖
            }
            else
            {
                indexes.Add(index + 1); // ↗
                indexes.Add(index + 1 + world.Map.MapBase); // ↘
                indexes.Add(index - 1 + world.Map.MapBase); // ↙
                indexes.Add(index - 1); // ↖
            }
            return indexes.Where(index => index > -1 && index < world.Map.Tiles.Count()).ToList();
        }

        public static IEnumerable<Tile> GetAdjacentTiles(World world, int index)
        {
            return world.Map.Tiles.Where(tile => GetAdjacentTileIndexes(world, index).Contains(tile.Key)).Select(tile => tile.Value);
        }

        public static void ExploreFromTile(World world, Player player, int index, int sightRange = 1) {
            //TODO: Take in to account e.g. visibility range, terrain type of the index, terrain type of the surrounding area etc.
            player.ExploredTileIndexes.UnionWith(GetAdjacentTileIndexes(world, index));
        }
    }
}
