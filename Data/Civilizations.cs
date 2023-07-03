using State.Enums;
using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Data
{
    public class Civilizations
    {
        public static Dictionary<CivilizationType, Civilization> ByType = new Dictionary<CivilizationType, Civilization>();

        internal static void Init()
        {
            Console.WriteLine("Initialize civilizations...");
            ByType = new Dictionary<CivilizationType, Civilization>
            {
                { CivilizationType.Babylonians, new Civilization(CivilizationType.Babylonians) },
                { CivilizationType.Chinese, new Civilization(CivilizationType.Chinese) },
                { CivilizationType.Norwegian, new Civilization(CivilizationType.Norwegian) }
            };
        }
    }
}
