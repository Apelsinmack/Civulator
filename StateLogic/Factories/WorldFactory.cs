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
            var unitFactory = new UnitFactory();
            var random = new Random();

            Map map = mapFactory.GenerateMap(mapBase, mapHeight);
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
                        unitFactory.GenerateUnit(UnitType.Warrior, player, map.Tiles[randomIndex], mapBase);
                        unitFactory.GenerateUnit(UnitType.Scout, player, map.Tiles[randomIndex + 1], mapBase); //TODO: Check if other side of the edge?
                        break;
                    }
                }
                while (true);
            });

            return new World(map, players);
        }
    }
}
