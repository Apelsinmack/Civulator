using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Text.Json;

namespace Api.IncomingCommands
{
    public class NewGame
    {
        public int MapBase { get; set; }
        public int MapHeight { get; set; }
        public List<Player> Players { get; set; }

        public NewGame(int mapBase, int mapHeight, List<Player> players)
        {
            MapBase = mapBase;
            MapHeight = mapHeight;
            Players = players;
        }
    }
}
