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
    public class UnitOrder : IAction
    {
        private readonly UnitOrderType _order;

        public ActionType Type => ActionType.UnitOrder;
        public UnitOrderType Order => _order;

        public UnitOrder(UnitOrderType order)
        {
            _order = order;
        }

        public string Serialize()
        {
            return JsonSerializer.Serialize(this);
        }
    }
}
