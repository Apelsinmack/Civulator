using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public class TileLogic : ITileLogic
    {
        private readonly ITerrainLogic _terrainLogic;

        public TileLogic(ITerrainLogic terrainLogic)
        {
            _terrainLogic = terrainLogic;
        }

        public Tile GenerateTile(int index)
        {
            return new Tile(index, _terrainLogic.GenerateTerrain());
        }
    }
}
