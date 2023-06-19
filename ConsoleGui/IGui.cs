using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Gui
{
    public interface IGui
    {
        public void PrintWorld(World world, List<string> log);
    }
}
