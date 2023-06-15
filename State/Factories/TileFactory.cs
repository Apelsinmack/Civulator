﻿using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State.Factories
{
    internal class TileFactory
    {
        TerrainFactory terrainFactory = new TerrainFactory();

        public Tile GenerateTile(int index)
        {
            return new Tile(index, terrainFactory.GenerateTerrain());
        }
    }
}
