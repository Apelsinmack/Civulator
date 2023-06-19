using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace Api.IncomingCommands
{
    public interface IIncomingCommand
    {
        public IncomingCommandType Type { get; }
    }
}
