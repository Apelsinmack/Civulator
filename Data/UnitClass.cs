using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Data
{
    public class UnitClass
    {
        public static Dictionary<UnitClassType, UnitClass> ByType = new Dictionary<UnitClassType, UnitClass>();

        public readonly int MeleeStrength;
        public readonly int Movement;
        public readonly int SightRange;

        public UnitClass(int meleeStrength, int movement, int sightRange)
        {
            MeleeStrength = meleeStrength;
            Movement = movement;
            SightRange = sightRange;
        }

        internal static void InitUnitClasses()
        {
            Console.WriteLine("Initialize unit classes...");
            ByType = new Dictionary<UnitClassType, UnitClass>
            {
                { UnitClassType.Scout, new UnitClass(10, 3, 2) },
                { UnitClassType.Settler, new UnitClass(0, 2, 3) },
                { UnitClassType.Warrior, new UnitClass(20, 2, 2) }
            };
        }
    }
}
