using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    [Serializable]
    public class Leader
    {
        public LeaderType Type { get; set; }
        public CivilizationType CivilizationType { get; set; }
        public ConsoleColor Color { get; set; }

        public Leader(LeaderType type, CivilizationType civilizationType, ConsoleColor color)
        {
            Type = type;
            CivilizationType = civilizationType;
            Color = color;
        }
    }
}
