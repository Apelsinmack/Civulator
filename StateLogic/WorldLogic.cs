using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public class WorldLogic
    {
        private World? _world;
        public World? World => _world;

        public WorldLogic() { }

        public World GenerateWorld(int mapBase, int mapHeight, List<Player> players)
        {
            var random = new Random();
            TerrainLogic terrainLogic = new TerrainLogic();
            TileLogic tileLogic = new TileLogic(terrainLogic);
            Map map = new MapLogic(tileLogic).GenerateMap(mapBase, mapHeight);
            _world = new World(map, players);
            HashSet<int> illegalIndexes = new();
            _world.Players.ForEach(player =>
            {
                do
                {
                    int randomIndex = random.Next(map.Tiles.Count);
                    if (!illegalIndexes.Contains(randomIndex))
                    {
                        foreach (int illegalIndex in GetAdjacentTiles(_world, randomIndex).Select(tile => tile.Index))
                        {
                            illegalIndexes.Add(illegalIndex);
                        }
                        illegalIndexes.Add(randomIndex);
                        UnitLogic.GenerateUnit(_world, UnitType.Settler, player, randomIndex);
                        UnitLogic.GenerateUnit(_world, UnitType.Warrior, player, randomIndex + 1); //TODO: Check if outside the map
                        break;
                    }
                }
                while (true);
            });

            return _world;
        }

        //TODO: Make non static?
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

        //TODO: Make non static?
        public static IEnumerable<Tile> GetAdjacentTiles(World world, int index)
        {
            return world.Map.Tiles.Where(tile => GetAdjacentTileIndexes(world, index).Contains(tile.Key)).Select(tile => tile.Value);
        }
    }
}
