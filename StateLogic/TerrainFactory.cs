using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic
{
    internal static class TerrainLogic
    {   
        private static TerrainType GetRandomTerrainType()
        {
            TerrainType[] terrainTypes = Enum.GetValues<TerrainType>();
            int index = new Random().Next(terrainTypes.Length);
            return (TerrainType)terrainTypes.GetValue(index);
        }

        public static Terrain GenerateTerrain()
        {
            return new Terrain(GetRandomTerrainType());
        }
    }
}
