using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic
{
    public static class WorldLogic
    {
        public static World GenerateWorld(int mapBase, int mapHeight, List<Player> players)
        {
            var random = new Random();

            Map map = MapLogic.GenerateMap(mapBase, mapHeight);
            World world = new World(map, players);

            HashSet<int> illegalIndexes = new();
            world.Players.ForEach(player =>
            {
                do
                {
                    int randomIndex = random.Next(map.Tiles.Count);
                    if (!illegalIndexes.Contains(randomIndex))
                    {
                        foreach (int illegalIndex in MapLogic.GetAdjacentTiles(world, randomIndex).Select(tile => tile.Index))
                        {
                            illegalIndexes.Add(illegalIndex);
                        }
                        illegalIndexes.Add(randomIndex);
                        CityLogic.GenerateCity(world, player, map.Tiles[randomIndex]);
                        UnitLogic.GenerateUnit(world, UnitType.Warrior, player, randomIndex);
                        UnitLogic.GenerateUnit(world, UnitType.Scout, player, randomIndex + 1); //TODO: Check if outside the map
                        break;
                    }
                }
                while (true);
            });

            return world;
        }
    }
}
