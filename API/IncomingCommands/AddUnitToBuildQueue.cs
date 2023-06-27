using Api.IncomingCommands.Enums;
using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Api.IncomingCommands
{
    public class AddUnitToBuildQueue
    {
        public City City { get; set; }
        public UnitType UnitType { get; set; }

        public AddUnitToBuildQueue(City city, UnitType unitType)
        {
            City = city;
            UnitType = unitType;
        }
    }
}
