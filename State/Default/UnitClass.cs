using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using State.Enums;

namespace State.Default
{
    public static class UnitClass
    {
        public static int Movment(UnitClassType unitClassType)
        {
            return unitClassType switch
            {
                UnitClassType.Scout => 3,
                UnitClassType.Settler => 2,
                UnitClassType.Warrior => 2,
                _ => 0
            };
        }

        public static int MeleeStrength(UnitClassType unitClassType)
        {
            return unitClassType switch
            {
                UnitClassType.Scout => 10,
                UnitClassType.Settler => 0,
                UnitClassType.Warrior => 20,
                _ => 0
            };
        }

        public static int SightRange(UnitClassType unitClassType)
        {
            return unitClassType switch
            {
                UnitClassType.Scout => 2,
                UnitClassType.Settler => 3,
                UnitClassType.Warrior => 2,
                _ => 0
            };
        }
    }
}
