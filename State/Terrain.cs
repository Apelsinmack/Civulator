using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    [Serializable]
    public class Terrain
    {
        public TerrainType Type { get; set; }

        public Terrain(TerrainType type)
        {
            Type = type;
        }
    }
}
