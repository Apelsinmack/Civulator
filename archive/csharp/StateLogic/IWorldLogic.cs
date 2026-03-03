using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public interface IWorldLogic
    {
        World World { get; }

        Player? CurrentPlayer { get; }

        IPlayerLogic PlayerLogic { get; }

        IUnitLogic UnitLogic { get; }

        ICityLogic CityLogic { get; }

        void SpawnPlayers();

        bool OnGoing();

        void InitTurn();

        IEnumerable<Tile> GetAdjacentTiles(int index);
    }
}
