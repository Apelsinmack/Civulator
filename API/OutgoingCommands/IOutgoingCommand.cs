using Api.OutgoingCommands;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace Api.OutgoingCommands
{
    public interface IOutgoingCommand
    {
        public OutgoingCommandType Type { get; }
    }
}
