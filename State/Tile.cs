using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    [Serializable]
    public class Tile
    {
        public int Index { get; set; }
        public Terrain Terrain { get; set; }
        public List<Unit> Units { get; set; }

        public Tile(int index, Terrain terrain, List<Unit> units)
        {
            Index = index;
            Terrain = terrain;
            Units = units;
        }
    }
}
