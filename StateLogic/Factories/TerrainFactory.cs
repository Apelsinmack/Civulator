using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic.Factories
{
    internal class TerrainFactory
    {
        private readonly Random _random = new Random();

        private TerrainType GetRandomTerrainType()
        {
            TerrainType[] terrainTypes = Enum.GetValues<TerrainType>();
            int index = _random.Next(terrainTypes.Length);
            return (TerrainType)terrainTypes.GetValue(index);
        }

        public Terrain GenerateTerrain()
        {
            return new Terrain(GetRandomTerrainType());
        }
    }
}
