using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    [Serializable]
    public class Victory
    {
        public Player Player { get; set; }

        public Victory(Player player)
        {
            Player = player;
        }
    }
}
