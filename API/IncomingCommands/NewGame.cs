using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Text.Json;

namespace Api.IncomingCommands
{
    [Serializable]
    public class NewGame : IIncomingCommand
    {
        public IncomingCommandType Type => IncomingCommandType.NewGame;
        public int MapBase { get; set; }
        public int MapHeight { get; set; }
        public List<Player> Players { get; set; }

        public NewGame() { }

        public NewGame(int mapBase, int mapHeight, List<Player> players)
        {
            MapBase = mapBase;
            MapHeight = mapHeight;
            Players = players;
        }

        public NewGame(string serializedObject)
        {
            NewGame newGame = JsonSerializer.Deserialize<NewGame>(serializedObject);
            MapBase= newGame.MapBase;
            MapHeight = newGame.MapHeight;
            Players = newGame.Players;
        }

        public byte[] Serialize()
        {
            return Encoding.UTF8.GetBytes(JsonSerializer.Serialize(this));
        }

        public static NewGame Deserialize(byte[] data)
        {
            return JsonSerializer.Deserialize<NewGame>(data);
        }
    }
}
