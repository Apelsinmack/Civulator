using Api.IncomingCommands;
using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace Api.OutgoingCommands
{
    public class NewState
    {
        public World World{ get; set; }

        public NewState(World world)
        {
            World = world;
        }
    }
}
