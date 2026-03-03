using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection.Metadata.Ecma335;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    [Serializable]
    public class Player
    {
        public Guid Id { get; set; }
        public string Name { get; set; }
        public bool Human { get; set; }
        public bool Dead { get; set; }
        public Leader Leader { get; set; }
        public int Turn { get; set; }
        public HashSet<int> ExploredTileIndexes { get; set; }
        public HashSet<int> VisibleTileIndexes { get; set; }
        public HashSet<int> UnitIndexes { get; set; }

        public Player(Guid id, string name, bool human, Leader leader)
        {
            Id = id;
            Name = name;
            Human = human;
            Leader = leader;
            ExploredTileIndexes = new HashSet<int>();
            VisibleTileIndexes = new HashSet<int>();
            UnitIndexes = new HashSet<int>();
        }
    }
}
