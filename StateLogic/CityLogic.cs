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
        private readonly Random _random;
        private City? _city;

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
            _random = new Random();
        }

        public void SetCurrentCity(City? city)
        {
            _city = city;
        }

        public IEnumerable<City> GetCities(Player player)
        {
            return _world.Map.Tiles.Where(tile => tile.Value.City != null && tile.Value.City.Owner == player).Select(tile => tile.Value.City);
        }

        public void AddProductionToCities(Player player, IUnitLogic unitLogic)
        {
            foreach (var city in GetCities(player))
            {
                //TODO: Calculate new city production
                city.AccumulatedProduction += city.Production;
                int productionCost = GetProductionCostOfNextItemInBuildingQueue(city);

                if (productionCost >= 0 && city.AccumulatedProduction >= productionCost)
                {
                    city.AccumulatedProduction -= productionCost;
                    if (city.BuildingQueue[0].UnitType.HasValue)
                    {
                        unitLogic.GenerateUnit(city.BuildingQueue[0].UnitType.Value, player, city.TileIndex);
                    }
                    else if (city.BuildingQueue[0].BuildingType.HasValue)
                    {
                        city.Buildings.Add(city.BuildingQueue[0].BuildingType.Value);
                    }
                    city.BuildingQueue.RemoveAt(0);
                }
            }
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
            City city = new City(GetNextCityName(owner), owner, tile.Index, MapLogic.GetAdjacentTileIndexes(_world.Map, tile.Index));
            tile.City = city;
            MapLogic.ExploreFromTile(_world, owner, tile.Index, 2);

            return city;
        }

        public IEnumerable<City>? GetCitiesWithEmptyBuildQueue(Player player)
        {
            return GetAllCities(player).Where(city => city.BuildingQueue.Count() == 0);
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
    }
}
