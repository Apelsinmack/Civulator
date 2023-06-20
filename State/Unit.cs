using State.Enums;
using State.Default;
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
        public int Movement => UnitClass.Movment(Class);
        public int MeleeStrength => UnitClass.MeleeStrength(Class);
        public int SightRange => UnitClass.SightRange(Class);

        public Unit(UnitClassType @class, Player owner, int tileIndex)
        {
            Id = Guid.NewGuid();
            Class = @class;
            Owner = owner;
            TileIndex = tileIndex;
        }
    }
}
