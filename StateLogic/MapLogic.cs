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

        public static List<int> GetAdjacentTileIndexes(Map map, int index)
        {
            List<int> indexes = new()
            {
                index - map.MapBase, // ↑
                index + map.MapBase // ↓
            };

            if (index % map.MapBase % 2 == 0)
            {
                indexes.Add(index - map.MapBase + 1); // ↗
                indexes.Add(index + 1); // ↘
                indexes.Add(index - 1); // ↙
                indexes.Add(index - 1 - map.MapBase); // ↖
            }
            else
            {
                indexes.Add(index + 1); // ↗
                indexes.Add(index + 1 + map.MapBase); // ↘
                indexes.Add(index - 1 + map.MapBase); // ↙
                indexes.Add(index - 1); // ↖
            }

            return indexes.Where(index => index > -1 && index < map.Tiles.Count()).ToList();
        }

        public static void ExploreFromTile(World world, Player player, int index, int sightRange = 1)
        {
            //TODO: Take in to account e.g. visibility range, terrain type of the index, terrain type of the surrounding area etc.
            player.ExploredTileIndexes.Add(index);
            player.ExploredTileIndexes.UnionWith(GetAdjacentTileIndexes(world.Map, index));
        }
    }
}
