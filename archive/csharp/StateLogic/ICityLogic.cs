using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public interface ICityLogic
    {
        void SetCurrentCity(City? city);

        City GenerateCity(Player owner, Tile tile);

        IEnumerable<City> GetCities(Player player);

        void AddProductionToCities(Player owner, IUnitLogic unitLogic);

        void AddBuildingToQueue(BuildingType buildingType);

        void AddUnitToQueue(UnitType unitType);

        void RemoveFromBuildQueue(int index);

        bool IsBuildingQueueEmpty();

        IEnumerable<City>? GetCitiesWithEmptyBuildQueue(Player player);

        IEnumerable<City>? GetAllCities(Player player);
    }
}
