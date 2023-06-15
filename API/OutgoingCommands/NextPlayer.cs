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
    public class NextPlayer : IOutgoingCommand
    {
        public OutgoingCommandType Type => OutgoingCommandType.NextPlayer;
        public World World{ get; set; }

        public NextPlayer(World world)
        {
            World = world;
        }

        public NextPlayer(string serializedObject)
        {
            //NextPlayer NextPlayer = JsonSerializer.Deserialize<NextPlayer>(serializedObject);
            //World = NextPlayer.World;
        }

        public string Serialize()
        {
            return "TODO";
            //return JsonSerializer.Serialize(this);
        }
    }
}
