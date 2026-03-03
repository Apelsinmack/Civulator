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
        public City? City { get; set; }
        public HashSet<int> UnitIndexes { get; set; }

        public Tile(int index, Terrain terrain)
        {
            Index = index;
            Terrain = terrain;
            UnitIndexes = new HashSet<int>();
        }
    }
}
