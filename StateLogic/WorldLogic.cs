using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public class WorldLogic : IWorldLogic
    {
        private readonly IPlayerLogic _playerLogic;
        private readonly IUnitLogic _unitLogic;
        private readonly ICityLogic _cityLogic;
        private World _world;
        private Player? _currentPlayer;

        public IPlayerLogic PlayerLogic => _playerLogic;
        public IUnitLogic UnitLogic => _unitLogic;
        public ICityLogic CityLogic => _cityLogic;
        public World World => _world;
        public Player? CurrentPlayer => _currentPlayer;

        public WorldLogic(World world, IPlayerLogic playerLogic, IUnitLogic unitLogic, ICityLogic cityLogic)
        {
            _world = world;
            _playerLogic = playerLogic;
            _unitLogic = unitLogic;
            _cityLogic = cityLogic;
        }

        public void SpawnPlayers()
        {
            var random = new Random();
            HashSet<int> illegalIndexes = new();
            _world.Players.ForEach(player =>
            {
                do
                {
                    int randomIndex = random.Next(_world.Map.Tiles.Count);
                    if (!illegalIndexes.Contains(randomIndex))
                    {
                        foreach (int illegalIndex in GetAdjacentTiles(randomIndex).Select(tile => tile.Index))
                        {
                            illegalIndexes.Add(illegalIndex);
                        }
                        illegalIndexes.Add(randomIndex);
                        _unitLogic.GenerateUnit(UnitType.Settler, player, randomIndex);
                        _unitLogic.GenerateUnit(UnitType.Warrior, player, randomIndex);
                        break;
                    }
                }
                while (true);
            });
        }

        public bool OnGoing()
        {
            return _world.Victory == null;
        }

        public void InitTurn()
        {
            _currentPlayer = _playerLogic.CurrentPlayer;
            _cityLogic.AddProductionToCities(_currentPlayer, _unitLogic);
            _unitLogic.ResetUnitMovements(_currentPlayer);
            _unitLogic.FortifyUnits(_currentPlayer);
        }

        public IEnumerable<Tile> GetAdjacentTiles(int index)
        {
            return _world.Map.Tiles.Where(tile => Logic.MapLogic.GetAdjacentTileIndexes(_world.Map, index).Contains(tile.Key)).Select(tile => tile.Value);
        }
    }
}
