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
    public class UnitOrder : BaseAction
    {
        public UnitOrderType Order { get; set; }

        public UnitOrder(UnitOrderType order)
        {
            Type = ActionType.UnitOrder;
            Order = order;
        }
    }
}
