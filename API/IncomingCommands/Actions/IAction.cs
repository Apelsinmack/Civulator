using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace Api.IncomingCommands.Actions
{
    public interface IAction
    {
        public ActionType Type { get; }

        public string Serialize();
    }
}
