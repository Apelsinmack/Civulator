using System;
using System.Collections.Generic;
using System.Data;
using System.Diagnostics.Metrics;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using Game.Enums;
using State;
using State.Factories;
using Api;
using Api.IncomingCommands;
using Api.OutgoingCommands;
using System.Numerics;
using System.IO.Pipes;
using System.Reflection.PortableExecutable;

namespace Game
{
    public class Engine
    {
        private readonly Server _server;
        private Connection _connection;
        private World? _world;
        private Player? _victory = null;

        private int GetTileIndex(Tile currentTile, Direction direction)
        {
            int newIndex = -1;
            if (currentTile.Index % _world.Map.MapBase % 2 == 0)
            {
                newIndex = direction switch
                {
                    Direction.Up => currentTile.Index - _world.Map.MapBase,
                    Direction.UpRight => currentTile.Index - _world.Map.MapBase + 1,
                    Direction.DownRight => currentTile.Index + 1,
                    Direction.Down => currentTile.Index + _world.Map.MapBase,
                    Direction.DownLeft => currentTile.Index + _world.Map.MapBase - 1,
                    Direction.UpLeft => currentTile.Index - 1
                };
            }
            else
            {
                newIndex = direction switch
                {
                    Direction.Up => currentTile.Index - _world.Map.MapBase,
                    Direction.UpRight => currentTile.Index + 1,
                    Direction.DownRight => currentTile.Index + _world.Map.MapBase + 1,
                    Direction.Down => currentTile.Index + _world.Map.MapBase,
                    Direction.DownLeft => currentTile.Index + _world.Map.MapBase - 1,
                    Direction.UpLeft => currentTile.Index - 1
                };
            }
            if (newIndex < 0 || newIndex > _world.Map.Tiles.Count - 1)
            {
                return -1;
            }
            return newIndex;
        }

        private Direction ConsoleReadDirection()
        {
            bool valid = false;
            int direction = -1;
            while (!valid)
            {
                int.TryParse(Console.ReadLine(), out direction);
                if (direction >= 1 || direction <= 6)
                {
                    valid = true;
                }
            }
            return (Direction)direction;
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