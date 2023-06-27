using Api.IncomingCommands.Enums;
using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Api.IncomingCommands
{
    public class RemoveFromBuildQueue
    {
        public City City { get; set; }
        public int Index { get; set; }

        public RemoveFromBuildQueue(City city, int index)
        {
            City = city;
            Index = index;
        }
    }
}
