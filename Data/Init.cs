using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Data
{
    public static class Init
    {
        public static void All()
        {
            Console.WriteLine("Initialize data...");
            Civilizations.Init();
            Leaders.Init();
            CapitalNames.Init();
            CityNames.Init();
            UnitClass.Init();
            Buildings.Init();
        }
    }
}
