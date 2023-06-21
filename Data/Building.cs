using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Data
{
    public class Building
    {
        public static Dictionary<BuildingType, Building> ByType = new Dictionary<BuildingType, Building>();

        public readonly int Production;

        public Building(int production)
        {
            Production = production;
        }

        internal static void InitBuildings()
        {
            Console.WriteLine("Initialize buildings...");
            ByType = new Dictionary<BuildingType, Building>
            {
                { BuildingType.Granary, new Building(65) }
            };
        }
    }
}
