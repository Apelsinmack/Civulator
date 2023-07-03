using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    internal class TileLogic : ITileLogic
    {
        private readonly ITerrainLogic _terrainLogic;

        internal TileLogic(ITerrainLogic terrainLogic)
        {
            _terrainLogic = terrainLogic;
        }

        public Tile GenerateTile(int index)
        {
            return new Tile(index, _terrainLogic.GenerateTerrain());
        }
    }
}
