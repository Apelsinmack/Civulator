﻿using System;
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
        public Leader Leader { get; set; }
        public int Turn { get; set; }
        public List<int> DiscoveredTileIndexes { get; set; }
        public List<int> VisibleTileIndexes { get; set; }

        public Player(string name, bool human, Leader leader)
        {
            Id = Guid.NewGuid();
            Name = name;
            Human = human;
            Leader = leader;
            DiscoveredTileIndexes = new List<int>();
            VisibleTileIndexes = new List<int>();
        }

        public void NextTurn()
        {
            Turn++;
        }
    }
}
