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

        public Map GenerateMap(int mapWidth, int mapHeight)
        {
            Dictionary<int, Tile> tiles = new Dictionary<int, Tile>();

            for (int i = 0; i < mapWidth * mapHeight; i++)
            {
                tiles.Add(i, _tileLogic.GenerateTile(i));
            }

            return new Map(mapWidth, mapHeight, tiles);
        }

        public static List<int> GetAdjacentTileIndexes(Map map, int index)
        {
            bool isLeftEdge = (index) % map.MapWidth == 0;
            bool isRightEdge = (index + 1) % map.MapWidth == 0;
            int oddRowAdjustment = (index / map.MapWidth) % 2;

            List<int> indexes = new(){ };

            if (isLeftEdge) {
                indexes.Add(index - map.MapWidth + oddRowAdjustment); // ↗
                indexes.Add(index + 1); // →
                indexes.Add(index + map.MapWidth + oddRowAdjustment); // ↘
                indexes.Add(index + map.MapWidth + (1 - oddRowAdjustment) * (map.MapWidth - 1)); // ↙
                indexes.Add(index + map.MapWidth - 1); // ←
                indexes.Add(index - oddRowAdjustment * (map.MapWidth) - (1 - oddRowAdjustment)); // ↖

            }
            else if (isRightEdge) {
                indexes.Add(index - map.MapWidth - oddRowAdjustment * (map.MapWidth - 1)); // ↗
                indexes.Add(index - map.MapWidth + 1); // →
                indexes.Add(index + map.MapWidth - oddRowAdjustment * (map.MapWidth - 1)); // ↘
                indexes.Add(index + map.MapWidth - (1 - oddRowAdjustment)); // ↙
                indexes.Add(index - 1); // ←
                indexes.Add(index - map.MapWidth - (1 - oddRowAdjustment)); // ↖
            }
            else
            {
                indexes.Add(index - map.MapWidth + oddRowAdjustment); // ↗
                indexes.Add(index + 1); // →
                indexes.Add(index + map.MapWidth + oddRowAdjustment); // ↘
                indexes.Add(index + map.MapWidth - (1 - oddRowAdjustment)); // ↙
                indexes.Add(index - 1); // ←
                indexes.Add(index - map.MapWidth - (1 - oddRowAdjustment)); // ↖
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
