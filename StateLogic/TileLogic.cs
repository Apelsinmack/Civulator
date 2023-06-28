using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    internal class TileLogic
    {
        private TerrainLogic _terrainLogic;

        internal TileLogic()
        {
            _terrainLogic = new TerrainLogic();
        }

        internal Tile GenerateTile(int index)
        {
            return new Tile(index, _terrainLogic.GenerateTerrain());
        }
    }
}
