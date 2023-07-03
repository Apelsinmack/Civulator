using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Data
{
    public class CapitalNames
    {
        public static Dictionary<LeaderType, string> ByLeaderType = new Dictionary<LeaderType, string>();

        internal static void Init()
        {
            Console.WriteLine("Initialize capital names...");
            ByLeaderType = new Dictionary<LeaderType, string>
            {
                { LeaderType.Hammurabi, "Babylon" },
                { LeaderType.HaraldHardrada, "Nidaros" },
                { LeaderType.QinShiHuang, "Xi'an" },
            };
        }
    }
}
