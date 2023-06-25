using Api.IncomingCommands;
using Api;
using State;
using System;
using System.Collections.Generic;
using System.Data.Common;
using System.IO.Pipes;
using System.Threading.Tasks;
using Api.IncomingCommands.Enums;
using Api.OutgoingCommands;
using StateLogic;
using System.Numerics;
using Gui;

namespace TestClient
{
    public class Client
    {
        private readonly Api _api;
        private NamedPipeClientStream _namedPipeClientStream;
        private ConsoleGui _gui;
        private GameState _state;

        private enum PlayerMenu
        {
            CycleUnits,
            CycleAllUnits,
            CycleCities,
            CycleAllCities,
            EndTurn
        }

        private static void PrintMenu()
        {
            Console.WriteLine("Choose what to to do:");
            Console.WriteLine("1: Cycle units");
            Console.WriteLine("2: Cycle all units");
            Console.WriteLine("3: Cycle cities");
            Console.WriteLine("4: Cycle all cities");
            Console.WriteLine("e: End turn");
        }

        private PlayerMenu ConsoleReadPlayerMenu()
        {
            while (true)
            {
                switch (Console.ReadLine())
                {
                    case "1":
                        return PlayerMenu.CycleUnits;
                    case "2":
                        return PlayerMenu.CycleAllUnits;
                    case "3":
                        return PlayerMenu.CycleCities;
                    case "4":
                        return PlayerMenu.CycleAllCities;
                    case "e":
                        return PlayerMenu.EndTurn;
                }
            }
        }

        private UnitOrderType ConsoleReadUnitOrder()
        {
            while (true)
            {
                switch (Console.ReadLine())
                {
                    case "1":
                        return UnitOrderType.DownLeft;
                    case "2":
                        return UnitOrderType.Down;
                    case "3":
                        return UnitOrderType.DownRight;
                    case "4":
                        return UnitOrderType.UpLeft;
                    case "5":
                        return UnitOrderType.Up;
                    case "6":
                        return UnitOrderType.UpRight;
                    case "f":
                        return UnitOrderType.Fortify;
                }
            }
        }

        private void CycleUnits(Player currentPlayer, IEnumerable<KeyValuePair<int, Unit>>? units, List<UnitOrder> unitOrders)
        {
            foreach (var unit in units)
            {
                if (unit.Value.MovementLeft > 0)
                {
                    Console.WriteLine($"Move {unit.Value.Class}");
                    unitOrders.Add(new UnitOrder(ConsoleReadUnitOrder(), unit.Value));
                }
            }
        }

        public Client()
        {
            _api = Api.GetInstance();
            _gui = new ConsoleGui();
        }

        public void Start()
        {
            using (_namedPipeClientStream = new NamedPipeClientStream(".", "Civulator", PipeDirection.InOut))
            {
                Console.WriteLine("Connecting to server...");
                _namedPipeClientStream.Connect();
                _api.GenerateWorld(_namedPipeClientStream, 10, 10, 3);
                while (_namedPipeClientStream.IsConnected)
                {
                    PlayerMenu playerMenu;
                    do
                    {
                        GameState _state = _api.GetState(_namedPipeClientStream);
                        if (_state.World.Victory.Player != null)
                        {
                            Console.WriteLine($"Congratulations to the victory {_state.World.Victory.Player.Name}!");
                            Console.ReadLine();
                            return;
                        }
                        Player currentPlayer = PlayerLogic.GetCurrentPlayer(_state.World);
                        List<UnitOrder> unitOrders = new();
                        var endTurn = false;
                        _gui.PrintWorld(_state.World, new List<string>());
                        PrintMenu();
                        switch (playerMenu = ConsoleReadPlayerMenu())
                        {
                            case PlayerMenu.CycleUnits:
                                CycleUnits(currentPlayer, PlayerLogic.GetUnfortifiedUnits(_state.World, currentPlayer), unitOrders);
                                break;
                            case PlayerMenu.CycleAllUnits:
                                CycleUnits(currentPlayer, PlayerLogic.GetAllUnits(_state.World, currentPlayer), unitOrders);
                                break;
                            case PlayerMenu.CycleCities:
                                break;
                            case PlayerMenu.CycleAllCities:
                                break;
                            case PlayerMenu.EndTurn:
                                endTurn = true;
                                break;
                        }
                        _api.ExecuteCommands(_namedPipeClientStream, new Actions(unitOrders, endTurn));
                    }
                    while (playerMenu != PlayerMenu.EndTurn);
                }
            }
        }
    }
}