using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    public class Unit
    {
        public Guid Id { get; set; }
        public UnitType Type { get; set; }
        public Player Owner { get; set; }
        public Tile Tile { get; set; }

        public Unit(UnitType type, Player owner, Tile tile)
        {
            Id = Guid.NewGuid();
            Type = type;
            Owner = owner;
            Tile = tile;
        }
    }
}
