using System;
using System.Collections.Generic;
using System.Data;
using System.Diagnostics.Metrics;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using State;
using Api;
using Api.IncomingCommands;
using Api.OutgoingCommands;
using System.Numerics;
using System.IO.Pipes;
using System.Reflection.PortableExecutable;
using Api.IncomingCommands.Enums;
using Gui;
using StateLogic.Factories;
using StateLogic;

namespace Game
{
    public class Engine
    {
        private NamedPipeServerStream _namedPipeServerStream;
        private readonly Server _server;
        private World? _world;
        private ConsoleGui _gui;

        private int GetNewIndex(int currentIndex, UnitOrderType order)
        {
            int newIndex = -1;
            if (currentIndex % _world.Map.MapBase % 2 == 0)
            {
                newIndex = order switch
                {
                    UnitOrderType.Up => currentIndex - _world.Map.MapBase,
                    UnitOrderType.UpRight => currentIndex - _world.Map.MapBase + 1,
                    UnitOrderType.DownRight => currentIndex + 1,
                    UnitOrderType.Down => currentIndex + _world.Map.MapBase,
                    UnitOrderType.DownLeft => currentIndex - 1,
                    UnitOrderType.UpLeft => currentIndex - _world.Map.MapBase - 1,
                    _ => currentIndex
                };
            }
            else
            {
                newIndex = order switch
                {
                    UnitOrderType.Up => currentIndex - _world.Map.MapBase,
                    UnitOrderType.UpRight => currentIndex + 1,
                    UnitOrderType.DownRight => currentIndex + _world.Map.MapBase + 1,
                    UnitOrderType.Down => currentIndex + _world.Map.MapBase,
                    UnitOrderType.DownLeft => currentIndex + _world.Map.MapBase - 1,
                    UnitOrderType.UpLeft => currentIndex - 1,
                    _ => currentIndex
                };
            }
            if (newIndex < 0 || newIndex > _world.Map.Tiles.Count - 1)
            {
                return -1;
            }
            return newIndex;
        }

        private void GenerateWorld()
        {
            NewGame newGame = _server.GetNewGame(_namedPipeServerStream);
            WorldFactory worldFactory = new WorldFactory();
            _world = worldFactory.GenerateWorld(newGame.MapBase, newGame.MapHeight, newGame.Players);
            _gui.PrintWorld(_world, new List<string>());
        }

        private void Play()
        {
            if (_world == null)
            {
                throw new Exception("World have to be generated before playing the game.");
            }
            while (_world.Victory.Player == null)
            {
                foreach (var player in _world.Players)
                {
                    List<string> log = new List<string>
                    {
                        $"{player.Name} turn {player.Turn}"
                    };
                    PlayerLogic.InitPlayerTurn(_world, player);
                    _gui.PrintWorld(_world, log);
                    Actions actions;
                    do
                    {
                        actions = _server.GetActions(_namedPipeServerStream, _world);
                        if (UnitOrders(player, actions.UnitOrders, log)) { return; };
                        _gui.PrintWorld(_world, log);
                    }
                    while (!actions.EndTurn); //TODO: Or if no actions left
                    //TODO: Send state.
                    player.Turn++;
                }
            }
        }

        private bool UnitOrders(Player player, List<UnitOrder> unitOrders, List<string> log)
        {
            foreach (var unitOrder in unitOrders)
            {
                log.Add($"{unitOrder.Unit.Class} {unitOrder.Order}");
                if (unitOrder.Order == UnitOrderType.Fortify)
                {
                    _world.Units[unitOrder.Unit.Index].MovementLeft = 0;
                    _world.Units[unitOrder.Unit.Index].Fortifying = true;
                    continue;
                }
                int newTileIndex = GetNewIndex(unitOrder.Unit.TileIndex, unitOrder.Order);
                if (newTileIndex > -1)
                {
                    UnitLogic.MoveUnit(_world, unitOrder.Unit.Index, newTileIndex);
                    Tile newTile = _world.Map.Tiles[newTileIndex];
                    MapLogic.ExploreFromTile(_world, player, newTileIndex, Data.UnitClass.ByType[unitOrder.Unit.Class].SightRange);
                    if (newTile.City != null && newTile.City.Owner != player)
                    {
                        log.Add($"{newTile.City.Owner.Name} lost {newTile.City.Name} to {player.Name}");
                        if (CityLogic.GetCities(_world, newTile.City.Owner).Count() == 1)
                        {
                            PlayerLogic.KillPlayer(_world, newTile.City.Owner);
                            log.Add($"{newTile.City.Owner.Name} is no more");
                            if (_world.Players.Where(player => !player.Dead).Count() == 1)
                            {
                                _world.Victory.Player = player;
                                newTile.City.Owner = player;
                                _server.SendState(_namedPipeServerStream, _world);
                                return true;
                            }
                        }
                        newTile.City.Owner = player;
                    }
                }
            }
            return false;
        }

        public Engine()
        {
            _server = Server.GetInstance();
            _gui = new ConsoleGui();
            Data.Init.All();
        }

        public void Start()
        {
            using (_namedPipeServerStream = new NamedPipeServerStream("Civulator", PipeDirection.InOut, 1, PipeTransmissionMode.Byte))
            {
                Console.WriteLine("Waiting for client to connect...");
                _namedPipeServerStream.WaitForConnection();
                Console.WriteLine("Client connected.");
                GenerateWorld();
                Play();
                _gui.PrintWorld(_world, new List<string>() { $"Congratulations to the victory {_world.Victory.Player.Name}!" });
                Console.ReadLine();
            }
        }
    }
}