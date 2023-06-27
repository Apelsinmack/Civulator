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
        public int Index { get; set; }
        public UnitType Class { get; set; }
        public Player Owner { get; set; }
        public int TileIndex { get; set; }
        public int MovementLeft { get; set; }
        public bool Fortifying { get; set; }
        public bool Fortified { get; set; }

        public Unit(int index, UnitType @class, Player owner, int tileIndex, int movementLeft)
        {
            Index = index;
            Class = @class;
            Owner = owner;
            TileIndex = tileIndex;
            MovementLeft = movementLeft;
        }
    }
}
