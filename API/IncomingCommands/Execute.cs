using Api.IncomingCommands.Actions;
using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace Api.IncomingCommands
{
    public class Execute
    {
        public List<UnitOrder> UnitOrders { get; set; }
        public bool EndTurn { get; set; }

        public Execute(List<UnitOrder> unitOrders, bool endTurn = false)
        {
            UnitOrders = unitOrders;
            EndTurn = endTurn;
        }
    }
}
