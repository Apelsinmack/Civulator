using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic
{
    internal static class TileLogic
    {
        public static Tile GenerateTile(int index)
        {
            return new Tile(index, TerrainLogic.GenerateTerrain());
        }
    }
}
