using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    [Serializable]
    public class Player
    {
        public string Name { get; set; }
        public bool Human { get; set; }
        public Leader Leader { get; set; }
        public int Turn { get; set; }

        public Player(string name, bool human, Leader leader)
        {
            Name = name;
            Human = human;
            Leader = leader;
        }

        public void NextTurn()
        {
            Turn++;
        }
    }
}
