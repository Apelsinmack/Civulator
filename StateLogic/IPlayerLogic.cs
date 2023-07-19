using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public interface IPlayerLogic
    {
        Player CurrentPlayer { get; }

        void SetCurrentPlayer();

        void EndTurn();

        void Kill(Player player, IUnitLogic unitLogic);
    }
}
