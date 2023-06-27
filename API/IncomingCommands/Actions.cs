using Api.IncomingCommands;
using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace Api.IncomingCommands
{
    public class Actions
    {
        public List<UnitOrder> UnitOrders { get; set; }
        public List<CityOrder> CityOrders { get; set; }
        public bool EndTurn { get; set; }

        public Actions(List<UnitOrder>? unitOrders, List<CityOrder>? cityOrders, bool endTurn = false)
        {
            UnitOrders = unitOrders;
            CityOrders = cityOrders;
            EndTurn = endTurn;
        }
    }
}
