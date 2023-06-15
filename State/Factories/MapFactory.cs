using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State.Factories
{
    public class MapFactory
    {
        public List<Tile> GetAdjacentTiles(Map map, int index)
        {
            if (index % map.MapBase == 0)
            {
                return map.Tiles.Where(tile =>
                    tile.Key == index - map.MapBase || // ↑
                    tile.Key == index - map.MapBase + 1 || // ↗
                    tile.Key == index + 1 || // ↘
                    tile.Key == index + map.MapBase || // ↓
                    tile.Key == index - 1 || // ↙
                    tile.Key == index - 1 - map.MapBase // ↖
                ).Select(tile => tile.Value).ToList();
            }
            else
            {
                return map.Tiles.Where(tile =>
                    tile.Key == index - map.MapBase || // ↑
                    tile.Key == index + 1 || // ↗
                    tile.Key == index + 1 + map.MapBase || // ↘
                    tile.Key == index + map.MapBase || // ↓
                    tile.Key == index - 1 + map.MapBase || // ↙
                    tile.Key == index - 1 // ↖
                ).Select(tile => tile.Value).ToList();
            }
        }

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
    }
}
