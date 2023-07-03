using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Data
{
    public class Buildings
    {
        public static Dictionary<BuildingType, Building> ByType = new Dictionary<BuildingType, Building>();

        internal static void Init()
        {
            Console.WriteLine("Initialize buildings...");
            ByType = new Dictionary<BuildingType, Building>
            {
                { BuildingType.Granary, new Building(BuildingType.Granary, 65) }
            };
        }
    }
}
