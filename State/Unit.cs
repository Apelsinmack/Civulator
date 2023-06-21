using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    [Serializable]
    public class Unit
    {
        public Guid Id { get; set; }
        public UnitClassType Class { get; set; }
        public Player Owner { get; set; }
        public int TileIndex { get; set; }
        public int MovementLeft { get; set; }
        public bool Fortifying { get; set; }
        public bool Fortyfied { get; set; }

        public Unit(UnitClassType @class, Player owner, int tileIndex, int movementLeft)
        {
            Id = Guid.NewGuid();
            Class = @class;
            Owner = owner;
            TileIndex = tileIndex;
            MovementLeft = movementLeft;

        }
    }
}
