using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic.Factories
{
    public class CityFactory
    {
        public City GenerateCity(World world, Player owner, Tile tile)
        {
            City city = new City(owner, tile.Index);
            tile.City = city;
            MapLogic.ExploreFromTile(world, owner, tile.Index, 2);

            return city;
        }
    }
}
