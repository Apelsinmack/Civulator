using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    [Serializable]
    public class City
    {
        public string Name { get; set; }
        public Player Owner { get; set; }
        public int TileIndex { get; set; }
        public int Size { get; set; }
        public List<Building> Buildings { get; set; }

        public City(string name, Player owner, int tileIndex)
        {
            Name = name;
            Owner = owner;
            TileIndex = tileIndex;
            Size = 1;
        }
    }
}
