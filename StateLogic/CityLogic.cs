using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public class CityLogic : ICityLogic
    {
        private readonly World _world;
        private readonly City? _city;
        private readonly Random _random;

        private string GetNextCityName(Player player)
        {
            var cities = GetAllCities(player).Select(city => city.Name);
            if (cities.Any())
            {
                var cityNames = Data.CityNames.ByCivilizationType[player.Leader.CivilizationType].Where(cityName => !cities.Contains(cityName));
                int randomIndex = _random.Next(cityNames.Count());
                return cityNames.ElementAt(randomIndex);
            }
            else
            {
                return Data.CapitalNames.ByLeaderType[player.Leader.Type];
            }
        }

        public CityLogic(World world)
        {
            _world = world;
            _city = null;
            _random = new Random();
        }

        public CityLogic(World world, City city)
        {
            _world = world;
            _city = city;
            _random = new Random();
        }

        public void AddBuildingToQueue(BuildingType buildingType)
        {
            if (!HasBuilding(buildingType))
            {
                _city.BuildingQueue.Add(new BuildingQueueItem(buildingType, null));
            }
        }

        public bool HasBuilding(BuildingType buildingType)
        {
            return _city.Buildings.Any(building => building == buildingType);
        }

        public void AddUnitToQueue(UnitType unitType)
        {
            _city.BuildingQueue.Add(new BuildingQueueItem(null, unitType));
        }

        public void RemoveFromBuildQueue(int index)
        {
            _city.BuildingQueue.RemoveAt(index);
        }

        public bool IsBuildingQueueEmpty()
        {
            return !_city.BuildingQueue.Any();
        }

        public IEnumerable<City>? GetAllCities(Player player)
        {
            return _world.Map.Tiles.Values.Where(tile => tile.City != null && tile.City.Owner.Id == player.Id).Select(tile => tile.City);
        }

        public City GenerateCity(Player owner, Tile tile)
        {
            City city = new City(GetNextCityName(owner), owner, tile.Index, WorldLogic.GetAdjacentTileIndexes(_world, tile.Index));
            tile.City = city;
            UnitLogic.ExploreFromTile(_world, owner, tile.Index, 2);

            return city;
        }






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
                productionCost = Data.Buildings.ByType[city.BuildingQueue[0].BuildingType.Value].Production;
            }

            return productionCost;
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
