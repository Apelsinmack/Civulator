using Api.IncomingCommands.Enums;
using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.Claims;
using System.Text;
using System.Text.Json.Serialization;
using System.Threading.Tasks;

namespace Api.IncomingCommands
{
    public class CityOrder
    {
        public CityOrderType Order { get; set; }
        public City City { get; set; }
        public BuildingType? BuildingType { get; set; }
        public UnitType? UnitType { get; set; }
        public int? Index { get; set; }

        public CityOrder() { }

        //public CityOrder(CityOrderType order, City city, BuildingType? buildingType, UnitType? unitType, int? index)
        //{
        //    Order = order;
        //    City = city;
        //    BuildingType = buildingType;
        //    UnitType = unitType;
        //    Index = index;
        //}

        public CityOrder(CityOrderType order, City city, BuildingType buildingType)
        {
            Order = order;
            City = city;
            BuildingType = buildingType;
        }

        public CityOrder(CityOrderType order, City city, UnitType unitType)
        {
            Order = order;
            City = city;
            UnitType = unitType;
        }

        public CityOrder(CityOrderType order, City city, int index)
        {
            Order = order;
            City = city;
            Index = index;
        }
    }
}
