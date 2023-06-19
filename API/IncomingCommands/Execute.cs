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
    public class Execute : IIncomingCommand
    {
        public IncomingCommandType Type => IncomingCommandType.Actions;
        public List<BaseAction> Actions { get; set; }
        public bool EndTurn { get; set; }

        public Execute(List<BaseAction> actions, bool endTurn = false)
        {
            Actions = actions;
            EndTurn = endTurn;
        }
    }
}
