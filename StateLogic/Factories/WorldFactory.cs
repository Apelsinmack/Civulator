using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic.Factories
{
    public class WorldFactory
    {
        public World GenerateWorld(int mapBase, int mapHeight, List<Player> players)
        {
            var mapFactory = new MapFactory();
            var cityFactory = new CityFactory();
            var unitFactory = new UnitFactory();
            var random = new Random();

            Map map = mapFactory.GenerateMap(mapBase, mapHeight);
            World world = new World(map, players);

            HashSet<int> illegalIndexes = new();
            players.ForEach(player =>
            {
                do
                {
                    int randomIndex = random.Next(map.Tiles.Count);
                    if (!illegalIndexes.Contains(randomIndex))
                    {
                        foreach (int illegalIndex in MapLogic.GetAdjacentTiles(map, randomIndex).Select(tile => tile.Index))
                        {
                            illegalIndexes.Add(illegalIndex);
                        }
                        illegalIndexes.Add(randomIndex);
                        cityFactory.GenerateCity(world, player, map.Tiles[randomIndex]);
                        unitFactory.GenerateUnit(world, UnitClassType.Warrior, player, map.Tiles[randomIndex]);
                        unitFactory.GenerateUnit(world, UnitClassType.Scout, player, map.Tiles[randomIndex + 1]); //TODO: Check if not outside the map
                        break;
                    }
                }
                while (true);
            });

            return world;
        }
    }
}
