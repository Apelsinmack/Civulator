using State.Enums;
using System;
using System.Collections.Generic;
using System.Drawing;
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
        public List<int> TileIndexes { get; set; }
        public int Size { get; set; }
        public List<BuildingType> Buildings { get; set; }
        public List<BuildingQueueItem> BuildingQueue { get; set; }
        public float Production { get; set; }
        public float AccumulatedProduction { get; set; }

        public City(string name, Player owner, int tileIndex, List<int> tileIndexes)
        {
            Name = name;
            Owner = owner;
            TileIndex = tileIndex;
            TileIndexes = tileIndexes;
            Size = 1;
            Buildings = new List<BuildingType>();
            BuildingQueue = new List<BuildingQueueItem>();
            Production = 5;
        }
    }
}
