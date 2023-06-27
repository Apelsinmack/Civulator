using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic
{
    public static class PlayerLogic
    {
        public static Player GeneratePlayer(string name, bool human, Leader leader)
        {
            return new Player(Guid.NewGuid(), name, human, leader);
        }

        public static Player GetCurrentPlayer(World world)
        {
            int currentTurn = world.Players.Where(player => !player.Dead).Min(Player => Player.Turn);
            return world.Players.Find(player => player.Turn == currentTurn && !player.Dead);
        }

        public static IEnumerable<Player> GetAlivePlayer(World world)
        {
            return world.Players.Where(player => !player.Dead);
        }

        public static void InitPlayerTurn(World world, Player player)
        {
            CityLogic.AddProductionToCities(world, player);
            UnitLogic.ResetUnitMovements(world, player);
            UnitLogic.FortifyUnits(world, player);
        }

        public static void KillPlayer(World world, Player player)
        {
            player.Dead = true;
            foreach (int index in player.UnitIndexes.ToList())
            {
                UnitLogic.RemoveUnit(world, index);
            }
        }

        public static IEnumerable<KeyValuePair<int, Unit>>? GetUnfortifiedUnits(World world, Player player)
        {
            return world.Units.Where(unit => player.UnitIndexes.Contains(unit.Key) && !unit.Value.Fortifying && !unit.Value.Fortified);
        }

        public static IEnumerable<KeyValuePair<int, Unit>>? GetAllUnits(World world, Player player)
        {
            return world.Units.Where(unit => player.UnitIndexes.Contains(unit.Key));
        }

        public static IEnumerable<City>? GetCitiesWithEmptyBuildQueue(World world, Player player)
        {
            return GetAllCities(world, player).Where(city => city.BuildingQueue.Count() == 0);
        }

        public static IEnumerable<City>? GetAllCities(World world, Player player)
        {
            return world.Map.Tiles.Values.Where(tile => tile.City != null && tile.City.Owner.Id == player.Id).Select(tile => tile.City);
        }
    }
}
