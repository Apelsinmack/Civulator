using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    internal class TerrainLogic : ITerrainLogic
    {
        private readonly Random _random;

        internal TerrainLogic()
        {
            _random = new Random();
        }

        private TerrainType GetRandomTerrainType()
        {
            TerrainType[] terrainTypes = Enum.GetValues<TerrainType>();
            int index = _random.Next(terrainTypes.Length);
            return (TerrainType)terrainTypes.GetValue(index);
        }

        public Terrain GenerateTerrain()
        {
            var randomTerrainType = GetRandomTerrainType();
            return new Terrain(randomTerrainType);
        }
    }
}
