using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    [Serializable]
    public class Civilization
    {
        public readonly CivilizationType Type;

        public Civilization(CivilizationType type)
        {
            Type = type;
        }
    }
}
