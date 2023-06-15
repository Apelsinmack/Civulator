using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    public class Tile
    {
        public int Index { get; set; }
        public Terrain Terrain { get; set; }
        public List<Unit> Units { get; set; }


        public Tile(int id, Terrain terrain)
        {
            Index = id;
            Terrain = terrain;
            Units = new List<Unit>();
        }
    }
}
