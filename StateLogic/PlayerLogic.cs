using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public class PlayerLogic
    {
        private readonly IUnitLogic? _unitLogic;
        private readonly World _world;
        private Player _currentPlayer;
        public Player CurrentPlayer => _currentPlayer;

        private void SetCurrentPlayer()
        {
            int currentTurn = _world.Players.Where(player => !player.Dead).Min(Player => Player.Turn);
            _currentPlayer = _world.Players.Find(player => player.Turn == currentTurn && !player.Dead);
        }

        public PlayerLogic(IUnitLogic unitLogic, World world)
        {
            _unitLogic = unitLogic;
            _world = world;
            SetCurrentPlayer();
        }

        public PlayerLogic(World world)
        {
            _world = world;
            SetCurrentPlayer();
        }

        public void EndTurn()
        {
            _currentPlayer.Turn++;
            SetCurrentPlayer();
        }

        public void InitPlayerTurn()
        {
            CityLogic.AddProductionToCities(_world, _currentPlayer);
            UnitLogic.ResetUnitMovements(_world, _currentPlayer);
            UnitLogic.FortifyUnits(_world, _currentPlayer);
        }

        public void Kill(Player player)
        {
            player.Dead = true;
            _unitLogic.DisbandAllUnits(player);
        }

        //TODO: Move to unit logic
        public IEnumerable<KeyValuePair<int, Unit>>? GetUnfortifiedUnits(Player player)
        {
            return _world.Units.Where(unit => player.UnitIndexes.Contains(unit.Key) && !unit.Value.Fortifying && !unit.Value.Fortified);
        }

        //TODO: Move to unit logic
        public IEnumerable<KeyValuePair<int, Unit>>? GetAllUnits(Player player)
        {
            return _world.Units.Where(unit => player.UnitIndexes.Contains(unit.Key));
        }

        //TODO: Move to city logic
        public IEnumerable<City>? GetCitiesWithEmptyBuildQueue(Player player)
        {
            return GetAllCities(player).Where(city => city.BuildingQueue.Count() == 0);
        }

        //TODO: Move to city logic
        public IEnumerable<City>? GetAllCities(Player player)
        {
            return _world.Map.Tiles.Values.Where(tile => tile.City != null && tile.City.Owner.Id == player.Id).Select(tile => tile.City);
        }
    }
}
