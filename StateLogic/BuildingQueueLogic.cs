using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic
{
    public class BuildingQueueLogic
    {
        public int GetProductionCostOfNextItem(Queue<BuildingQueueItem> buildingQueue)
        {
            var buildingQueueItem = buildingQueue.Peek();
            if (buildingQueueItem != null)
            {
                if (buildingQueueItem.UnitType.HasValue)
                {
                    return Data.UnitClass.ByType[buildingQueueItem.UnitType.Value].Production;
                }
                else if (buildingQueueItem.BuildingType.HasValue)
                {
                    return Data.Building.ByType[buildingQueueItem.BuildingType.Value].Production;
                }
                throw new Exception("Unknown type in production queue");
            }
            return 0;
        }
    }
}
