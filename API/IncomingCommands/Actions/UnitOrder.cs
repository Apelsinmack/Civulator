using Api.IncomingCommands.Actions.Enums;
using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace Api.IncomingCommands.Actions
{
    public class UnitOrder
    {
        public UnitOrderType Order { get; set; }
        public Unit Unit { get; set; }

        public UnitOrder(UnitOrderType order, Unit unit)
        {
            Order = order;
            Unit = unit;
        }
    }
}
