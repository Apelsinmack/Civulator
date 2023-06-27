using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic
{
    public static class CityLogic
    {
        private static string GetRandomCityName()
        {
            //TODO: Take care of too big index...
            var random = new Random();
            int randomIndex = random.Next(cities.Count);
            string city = cities[randomIndex];
            cities.RemoveAt(randomIndex);
            return city;
        }

        private static List<string> cities = new List<string>
            {
                "Malmö",
                "Lund",
                "Göteborg",
                "Eslöv",
                "Stockholm"
            };

        private static int GetProductionCostOfNextItemInBuildingQueue(City city)
        {
            if (city.BuildingQueue.Count() == 0)
            {
                return -1;
            }

            int productionCost = 0;
            if (city.BuildingQueue[0].UnitType.HasValue)
            {
                productionCost = Data.UnitClass.ByType[city.BuildingQueue[0].UnitType.Value].Production;
            }
            if (city.BuildingQueue[0].BuildingType.HasValue)
            {
                productionCost = Data.Building.ByType[city.BuildingQueue[0].BuildingType.Value].Production;
            }

            return productionCost;
        }

        public static City GenerateCity(World world, Player owner, Tile tile)
        {
            City city = new City(GetRandomCityName(), owner, tile.Index, MapLogic.GetAdjacentTileIndexes(world, tile.Index));
            tile.City = city;
            MapLogic.ExploreFromTile(world, owner, tile.Index, 2);

            return city;
        }

        public static IEnumerable<City> GetCities(World world, Player player)
        {
            return world.Map.Tiles.Where(tile => tile.Value.City != null && tile.Value.City.Owner == player).Select(tile => tile.Value.City);
        }

        public static void AddProductionToCities(World world, Player player)
        {
            var cities = GetCities(world, player);
            foreach (var city in cities)
            {
                //TODO: Calculate new city production
                city.AccumulatedProduction += city.Production;
                int productionCost = GetProductionCostOfNextItemInBuildingQueue(city);

                if (productionCost > -1 && city.AccumulatedProduction >= productionCost)
                {
                    city.AccumulatedProduction -= productionCost;
                    if (city.BuildingQueue[0].UnitType.HasValue)
                    {
                        UnitLogic.GenerateUnit(world, city.BuildingQueue[0].UnitType.Value, player, city.TileIndex);
                    }
                    if (city.BuildingQueue[0].BuildingType.HasValue)
                    {
                        city.Buildings.Add(city.BuildingQueue[0].BuildingType.Value);
                    }
                    city.BuildingQueue.RemoveAt(0);
                }
            }
        }
    }
}
