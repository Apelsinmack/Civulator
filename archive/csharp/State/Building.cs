using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    [Serializable]
    public class Building
    {
        public readonly BuildingType BuildingType;
        public readonly int Production;

        public Building(BuildingType buildingType, int production)
        {
            BuildingType = buildingType;
            Production = production;
        }
    }
}
