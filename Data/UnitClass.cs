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
        public static Dictionary<UnitType, UnitClass> ByType = new Dictionary<UnitType, UnitClass>();

        public readonly int MeleeStrength;
        public readonly int Movement;
        public readonly int SightRange;
        public readonly int Production;

        public UnitClass(int meleeStrength, int movement, int sightRange, int production)
        {
            MeleeStrength = meleeStrength;
            Movement = movement;
            SightRange = sightRange;
            Production = production;
        }

        internal static void InitUnitClasses()
        {
            Console.WriteLine("Initialize unit classes...");
            ByType = new Dictionary<UnitType, UnitClass>
            {
                { UnitType.Scout, new UnitClass(10, 3, 2, 30) },
                { UnitType.Settler, new UnitClass(0, 2, 3, 80) },
                { UnitType.Warrior, new UnitClass(20, 2, 2, 40) }
            };
        }
    }
}
