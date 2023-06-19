using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace Api.IncomingCommands.Actions
{
    public class BaseAction
    {
        public ActionType Type { get; set; }

        public BaseAction() { }
    }
}
