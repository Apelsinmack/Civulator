using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State.Factories
{
    public class PlayerFactory
    {
        public static Player GeneratePlayer(string name, bool human, Leader leader)
        {
            return new Player(name, human, leader);
        }
    }
}
