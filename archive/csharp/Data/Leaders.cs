using State.Enums;
using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Data
{
    public class Leaders
    {
        public static Dictionary<LeaderType, Leader> ByType = new Dictionary<LeaderType, Leader>();

        internal static void Init()
        {
            Console.WriteLine("Initialize leaders...");
            ByType = new Dictionary<LeaderType, Leader>
            {
                { LeaderType.Hammurabi, new Leader(LeaderType.Hammurabi, CivilizationType.Babylonians, ConsoleColor.Blue) },
                { LeaderType.HaraldHardrada, new Leader(LeaderType.HaraldHardrada, CivilizationType.Norwegian, ConsoleColor.Red) },
                { LeaderType.QinShiHuang, new Leader(LeaderType.QinShiHuang, CivilizationType.Chinese, ConsoleColor.Cyan) }
            };
        }
    }
}
