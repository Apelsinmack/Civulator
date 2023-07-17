using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public class PlayerLogic : IPlayerLogic
    {
        private World _world;
        private Player _currentPlayer;

        public Player CurrentPlayer => _currentPlayer;

        public PlayerLogic(World world)
        {
            _world = world;
            _currentPlayer = _world.Players[0];
        }

        public void SetCurrentPlayer()
        {
            int currentTurn = _world.Players.Where(player => !player.Dead).Min(Player => Player.Turn);
            _currentPlayer = _world.Players.Find(player => player.Turn == currentTurn && !player.Dead);
        }

        public void EndTurn()
        {
            _currentPlayer.Turn++;
            SetCurrentPlayer();
        }

        public void Kill(Player player, IUnitLogic unitLogic)
        {
            player.Dead = true;
            unitLogic.DisbandAllUnits(player);
        }
    }
}
