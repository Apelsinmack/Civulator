using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    [Serializable]
    public class BuildingQueueItem
    {
        public BuildingType? BuildingType { get; set; }
        public UnitType? UnitType { get; set; }

        public BuildingQueueItem(BuildingType? buildingType, UnitType? unitType)
        {
            BuildingType = buildingType;
            UnitType = unitType;
        }
    }
}
