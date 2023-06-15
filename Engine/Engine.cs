using System;
using System.Collections.Generic;
using System.Data;
using System.Diagnostics.Metrics;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using State;
using State.Factories;
using Api;
using Api.IncomingCommands;
using Api.OutgoingCommands;
using System.Numerics;
using System.IO.Pipes;
using System.Reflection.PortableExecutable;
using Api.IncomingCommands.Actions.Enums;

namespace Game
{
    public class Engine
    {
        private readonly Server _server;
        private Connection _connection;
        private World? _world;
        private Player? _victory = null;

        private int GetTileIndex(Tile currentTile, UnitOrderType order)
        {
            int newIndex = -1;
            if (currentTile.Index % _world.Map.MapBase % 2 == 0)
            {
                newIndex = order switch
                {
                    UnitOrderType.Up => currentTile.Index - _world.Map.MapBase,
                    UnitOrderType.UpRight => currentTile.Index - _world.Map.MapBase + 1,
                    UnitOrderType.DownRight => currentTile.Index + 1,
                    UnitOrderType.Down => currentTile.Index + _world.Map.MapBase,
                    UnitOrderType.DownLeft => currentTile.Index + _world.Map.MapBase - 1,
                    UnitOrderType.UpLeft => currentTile.Index - 1,
                    _ => currentTile.Index
                };
            }
            else
            {
                newIndex = order switch
                {
                    UnitOrderType.Up => currentTile.Index - _world.Map.MapBase,
                    UnitOrderType.UpRight => currentTile.Index + 1,
                    UnitOrderType.DownRight => currentTile.Index + _world.Map.MapBase + 1,
                    UnitOrderType.Down => currentTile.Index + _world.Map.MapBase,
                    UnitOrderType.DownLeft => currentTile.Index + _world.Map.MapBase - 1,
                    UnitOrderType.UpLeft => currentTile.Index - 1,
                    _ => currentTile.Index
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
            NewGame newGame = _server.GetNewGame(_connection);
            WorldFactory worldFactory = new WorldFactory();
            _world = worldFactory.GenerateWorld(newGame.MapBase, newGame.MapHeight, newGame.Players);
            ConsoleGui.PrintWorld(_world);
        }

        private void Play()
        {
            if (_world == null)
            {
                throw new Exception("World have to be generated before playing the game.");
            }
            while (_victory == null)
            {
                _world.Players[0].Turn++;
                Console.WriteLine();
                Console.WriteLine("------------------------------");
                Console.WriteLine("Turn: " + _world.Players[0].Turn);
                Console.WriteLine("------------------------------");
                foreach (var player in _world.Players)
                {
                    Console.WriteLine("Player: " + player.Name);
                    Execute execute;
                    do
                    {
                        execute = _server.GetActions(_connection, _world);
                        foreach(var action in execute.Actions)
                        {
                            Console.WriteLine("Move unit");
                            //TODO: Update state!
                        }
                    }
                    while (!execute.EndTurn);
                    Console.WriteLine("------------------------------");
                }
            }
            Console.WriteLine("Congratulations to the victory " + _victory.Name + "!");
        }

        public Engine()
        {
            _server = Server.GetInstance();
        }

        public void Start()
        {
            using (var pipeServer = new NamedPipeServerStream("Civ", PipeDirection.InOut))
            {
                Console.WriteLine("Waiting for client to connect...");
                pipeServer.WaitForConnection();
                Console.WriteLine("Client connected.");
                _connection = new Connection(pipeServer);
                GenerateWorld();
                Play();
            }
        }
    }
}