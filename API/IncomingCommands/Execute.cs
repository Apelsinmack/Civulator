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
        //public List<IAction> Actions { get; set; }
        public List<string> Actions { get; set; }
        public bool EndTurn { get; set; }

        public Execute()
        {
        }

        //public Execute(List<IAction> actions, bool endTurn = false)
        public Execute(List<string> actions, bool endTurn = false)
        {
            Actions = actions;
            EndTurn = endTurn;
        }

        public Execute(string serializedObject)
        {
            Execute execute = JsonSerializer.Deserialize<Execute>(serializedObject);
            Actions = execute.Actions;
            EndTurn = execute.EndTurn;
        }

        public string Serialize()
        {
            return JsonSerializer.Serialize(this);
        }
    }
}
