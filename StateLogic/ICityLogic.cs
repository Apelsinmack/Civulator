using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public interface ICityLogic
    {
        City GenerateCity(Player owner, Tile tile);
    }
}
