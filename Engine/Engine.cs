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
        private readonly Server _server;
        private World? _world;
        private Player? _victory = null;
        private IGui _gui;

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

        private void GenerateWorld(NamedPipeServerStream namedPipeServerStream)
        {
            NewGame newGame = _server.GetNewGame(namedPipeServerStream);
            WorldFactory worldFactory = new WorldFactory();
            _world = worldFactory.GenerateWorld(newGame.MapBase, newGame.MapHeight, newGame.Players);
            _gui.PrintWorld(_world, new List<string>());
        }

        private void Play(NamedPipeServerStream namedPipeServerStream)
        {
            if (_world == null)
            {
                throw new Exception("World have to be generated before playing the game.");
            }
            while (_victory == null)
            {
                foreach (var player in _world.Players)
                {
                    List<string> log = new List<string>
                    {
                        $"{player.Name} turn {player.Turn}"
                    };
                    _gui.PrintWorld(_world, log);
                    Actions actions;
                    do
                    {
                        actions = _server.GetActions(namedPipeServerStream, _world);
                        foreach (var unitOrder in actions.UnitOrders)
                        {
                            log.Add($"{unitOrder.Unit.Class.ToString()} {unitOrder.Order.ToString()}");
                            int newTileIndex = GetNewIndex(_world.Map.Tiles[unitOrder.Unit.TileIndex].Index, unitOrder.Order);
                            if (newTileIndex > -1)
                            {
                                _world.Map.Tiles[unitOrder.Unit.TileIndex].Units.RemoveAll(unit => unit.Id == unitOrder.Unit.Id);
                                unitOrder.Unit.TileIndex = newTileIndex;
                                _world.Map.Tiles[newTileIndex].Units.Add(unitOrder.Unit);
                                player.ExploredTileIndexes.UnionWith(MapLogic.GetAdjacentTileIndexes(_world.Map.MapBase, newTileIndex));
                            }
                        }
                        _gui.PrintWorld(_world, log);
                    }
                    while (!actions.EndTurn); //TODO: Or if no actions left
                    //TODO: Send state.
                    player.NextTurn();
                }
            }
            Console.WriteLine($"Congratulations to the victory {_victory.Name}!");
        }

        public Engine()
        {
            _server = Server.GetInstance();
            _gui = new ConsoleGui();
        }

        public void Start()
        {
            using (var namedPipeServerStream = new NamedPipeServerStream("Civulator", PipeDirection.InOut, 1, PipeTransmissionMode.Byte))
            {
                Console.WriteLine("Waiting for client to connect...");
                namedPipeServerStream.WaitForConnection();
                Console.WriteLine("Client connected.");
                GenerateWorld(namedPipeServerStream);
                Play(namedPipeServerStream);
            }
        }
    }
}