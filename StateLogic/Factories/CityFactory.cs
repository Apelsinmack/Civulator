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
            City city = new City(this.getRandomCityName(), owner, tile.Index);
            tile.City = city;
            MapLogic.ExploreFromTile(world, owner, tile.Index, 2);

            return city;
        }

        private string getRandomCityName()
        {
            //TODO: Take care of too big index...
            var random = new Random();
            int randomIndex = random.Next(cities.Count);
            string city = cities[randomIndex];
            cities.RemoveAt(randomIndex);
            return city;
        }

        private static List<string> cities = new List<string>
            {
                "Malmö",
                "Lund",
                "Göteborg",
                "Eslöv",
                "Stockholm"
            };
    }
}
