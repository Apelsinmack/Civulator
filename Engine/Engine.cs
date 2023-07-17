using Api;
using Api.IncomingCommands;
using Api.IncomingCommands.Enums;
using Data;
using Gui;
using Logic;
using State;
using State.Enums;
using System.Data;
using System.IO.Pipes;

namespace Game
{
    public class Engine
    {
        private NamedPipeServerStream _namedPipeServerStream;
        private readonly Server _server;
        private ConsoleMapGui _gui;
        private IWorldLogic _worldLogic;
        private IPlayerLogic _playerLogic;
        private IUnitLogic _unitLogic;
        private ICityLogic _cityLogic;

        private int GetNewIndex(int currentIndex, UnitOrderType order)
        {
            int mapBase = _worldLogic.World.Map.MapBase;
            int newIndex = -1;
            if (currentIndex % _worldLogic.World.Map.MapBase % 2 == 0)
            {
                newIndex = order switch
                {
                    UnitOrderType.Up => currentIndex - mapBase,
                    UnitOrderType.UpRight => currentIndex - mapBase + 1,
                    UnitOrderType.DownRight => currentIndex + 1,
                    UnitOrderType.Down => currentIndex + mapBase,
                    UnitOrderType.DownLeft => currentIndex - 1,
                    UnitOrderType.UpLeft => currentIndex - mapBase - 1,
                    _ => currentIndex
                };
            }
            else
            {
                newIndex = order switch
                {
                    UnitOrderType.Up => currentIndex - mapBase,
                    UnitOrderType.UpRight => currentIndex + 1,
                    UnitOrderType.DownRight => currentIndex + mapBase + 1,
                    UnitOrderType.Down => currentIndex + mapBase,
                    UnitOrderType.DownLeft => currentIndex + mapBase - 1,
                    UnitOrderType.UpLeft => currentIndex - 1,
                    _ => currentIndex
                };
            }
            if (newIndex < 0 || newIndex > _worldLogic.World.Map.Tiles.Count - 1)
            {
                return -1;
            }
            return newIndex;
        }

        private void Play()
        {
            while (_worldLogic.OnGoing())
            {
                _worldLogic.InitTurn();
                var player = _worldLogic.CurrentPlayer;
                List<string> log = new List<string>
                    {
                        $"{player.Name} turn {player.Turn}"
                    };
                
                _gui.PrintWorld(_worldLogic.World, player, log);
                Actions actions;
                do
                {
                    actions = _server.GetActions(_namedPipeServerStream, _worldLogic.World);

                    if (UnitOrders(player, actions, log)) { return; };
                    CityOrders(actions, log);
                    _gui.PrintWorld(_worldLogic.World, player, log);
                }
                while (!actions.EndTurn); //TODO: Or if no actions left
                //TODO: Send state?
                _playerLogic.EndTurn();
            }
        }

        private bool UnitOrders(Player player, Actions actions, List<string> log)
        {
            foreach (var unitOrder in actions.UnitOrders)
            {
                log.Add($"{unitOrder.Unit.Class} {unitOrder.Order}");
                _unitLogic.SetCurrentUnit(unitOrder.Unit);

                switch (unitOrder.Order)
                {
                    case UnitOrderType.Fortify:
                        _unitLogic.Fortify();
                        break;
                    case UnitOrderType.BuildCity:
                        _unitLogic.BuildCity(_cityLogic);
                        break;
                    default:
                        int newTileIndex = GetNewIndex(unitOrder.Unit.TileIndex, unitOrder.Order);

                        if (newTileIndex > -1)
                        {
                            _unitLogic.MoveUnit(newTileIndex);
                            Tile newTile = _worldLogic.World.Map.Tiles[newTileIndex];

                            if (newTile.City != null && newTile.City.Owner != player)
                            {
                                log.Add($"{newTile.City.Owner.Name} lost {newTile.City.Name} to {player.Name}");

                                if (_cityLogic.GetCities(newTile.City.Owner).Count() == 1)
                                {
                                    _playerLogic.Kill(newTile.City.Owner, _unitLogic);
                                    log.Add($"{newTile.City.Owner.Name} is no more");

                                    if (_worldLogic.World.Players.Where(player => !player.Dead).Count() == 1)
                                    {
                                        _worldLogic.World.Victory = new Victory(player);
                                        newTile.City.Owner = player;
                                        _server.SendState(_namedPipeServerStream, _worldLogic.World);
                                        return true;
                                    }
                                }
                                newTile.City.Owner = player;
                            }
                        }
                        break;
                }
            }
            return false;
        }

        private void CityOrders(Actions actions, List<string> log)
        {
            foreach (var cityOrder in actions.CityOrders)
            {
                _cityLogic.SetCurrentCity(_worldLogic.World.Map.Tiles[cityOrder.City.TileIndex].City);
                log.Add($"{cityOrder.City.Name} {cityOrder.Order}");

                switch (cityOrder.Order)
                {
                    case CityOrderType.AddBuildingToBuildQueue:
                        _cityLogic.AddBuildingToQueue(cityOrder.BuildingType.Value);
                        break;
                    case CityOrderType.AddUnitToBuildQueue:
                        _cityLogic.AddUnitToQueue(cityOrder.UnitType.Value);
                        break;
                    case CityOrderType.RemoveFromBuildQueue:
                        _cityLogic.RemoveFromBuildQueue(cityOrder.Index.Value);
                        break;
                }
                if (_cityLogic.IsBuildingQueueEmpty())
                {
                    actions.EndTurn = false;
                }
            }
        }

        public Engine()
        {
            _server = Server.GetInstance();
            _gui = new ConsoleMapGui(true);
            Init.All();
            ITerrainLogic terrainLogic = new TerrainLogic();
            ITileLogic tileLogic = new TileLogic(terrainLogic);
            IMapLogic mapLogic = new MapLogic(tileLogic);
            List<Player> players = new()
                {
                    new Player(Guid.NewGuid(), "Megadick", true, Leaders.ByType[LeaderType.HaraldHardrada]),
                    new Player(Guid.NewGuid(), "Ken Q", true, Leaders.ByType[LeaderType.Hammurabi]),
                    new Player(Guid.NewGuid(), "AnotherNerd", true, Leaders.ByType[LeaderType.QinShiHuang])
                };
            Map map = mapLogic.GenerateMap(20, 10);
            World world = new World(map, players);
            _playerLogic = new PlayerLogic(world);
            _unitLogic = new UnitLogic(world);
            _cityLogic = new CityLogic(world);
            _worldLogic = new WorldLogic(world, _playerLogic, _unitLogic, _cityLogic);
            _worldLogic.SpawnPlayers();
        }

        public void Start()
        {
            using (_namedPipeServerStream = new NamedPipeServerStream("Civulator", PipeDirection.InOut, 1, PipeTransmissionMode.Byte))
            {
                Console.WriteLine("Waiting for client to connect...");
                _namedPipeServerStream.WaitForConnection();
                Console.WriteLine("Client connected.");
                _gui.PrintWorld(_worldLogic.World, _playerLogic.CurrentPlayer, new List<string>());
                Play();
                _gui.PrintWorld(_worldLogic.World, _playerLogic.CurrentPlayer, new List<string>() { $"Congratulations to the victory {_worldLogic.World.Victory.Player.Name}!" });
                Console.ReadLine();
            }
        }
    }
}