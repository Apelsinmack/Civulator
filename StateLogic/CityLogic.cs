using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic
{
    public static class CityLogic
    {
        public static IEnumerable<City> GetCities(World world, Player player)
        {
            return world.Map.Tiles.Where(tile => tile.Value.City != null && tile.Value.City.Owner == player).Select(tile => tile.Value.City);
        }
    }
}
