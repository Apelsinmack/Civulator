using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace State
{
    public class Leader
    {
        public string Name { get; set; }
        public string Description { get; set; }
        public ConsoleColor Color { get; set; }

        public Leader(ConsoleColor color)
        {
            Color = color;
        }
    }
}
