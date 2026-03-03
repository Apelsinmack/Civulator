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
using Logic;
using System.Numerics;
using Gui;
using State.Enums;

namespace TestClient
{
    public class Client
    {
        private readonly Api _api;
        private NamedPipeClientStream _namedPipeClientStream;
        private ConsoleMapGui _mapGui;
        private ConsoleClientGui _clientGui;
        private GameState _state;
        private IWorldLogic _worldLogic;
        private IPlayerLogic _playerLogic;
        private IUnitLogic _unitLogic;
        private ICityLogic _cityLogic;

        private void CycleUnits(IEnumerable<KeyValuePair<int, Unit>>? units, List<UnitOrder> unitOrders)
        {
            foreach (var unit in units)
            {
                if (unit.Value.MovementLeft > 0)
                {
                    Console.WriteLine($"Move {unit.Value.Class}");
                    unitOrders.Add(new UnitOrder(_clientGui.ConsoleReadUnitOrder(unit.Value.Class), unit.Value));
                }
            }
        }

        private void CycleCities(IEnumerable<City> cities, List<CityOrder> cityOrders)
        {
            foreach (var city in cities)
            {
                ConsoleClientGui.BuildTypeMenu buildingTypeMenu = _clientGui.PrintBuildAddToBuildQueueMenu(city);
                if (buildingTypeMenu == ConsoleClientGui.BuildTypeMenu.Units)
                {
                    cityOrders.Add(new CityOrder(CityOrderType.AddUnitToBuildQueue, city, _clientGui.PrintBuildUnitMenu(city)));
                }
                else if (buildingTypeMenu == ConsoleClientGui.BuildTypeMenu.Buildings)
                {
                    cityOrders.Add(new CityOrder(CityOrderType.AddBuildingToBuildQueue, city, _clientGui.PrintBuildBuildingMenu(city)));
                }

            }
        }

        public Client()
        {
            _api = Api.GetInstance();
            _mapGui = new ConsoleMapGui();
            _clientGui = new ConsoleClientGui();
        }

        public void Start()
        {
            Data.Init.All();
            using (_namedPipeClientStream = new NamedPipeClientStream(".", "Civulator", PipeDirection.InOut))
            {
                Console.WriteLine("Connecting to server...");
                _namedPipeClientStream.Connect();

                while (_namedPipeClientStream.IsConnected)
                {
                    ConsoleClientGui.PlayerMenu playerMenu;
                    do
                    {
                        GameState _state = _api.GetState(_namedPipeClientStream);
                        _playerLogic = new PlayerLogic(_state.World);
                        _unitLogic = new UnitLogic(_state.World);
                        _cityLogic = new CityLogic(_state.World);
                        _worldLogic = new WorldLogic(_state.World, _playerLogic, _unitLogic, _cityLogic);
                        if (_state.World.Victory != null)
                        {
                            Console.WriteLine($"Congratulations to the victory {_state.World.Victory.Player.Name}!");
                            Console.ReadLine();
                            return;
                        }
                        _playerLogic.SetCurrentPlayer();
                        var player = _playerLogic.CurrentPlayer;
                        List<UnitOrder> unitOrders = new();
                        List<CityOrder> cityOrders = new();
                        var endTurn = false;
                        _mapGui.PrintWorld(_state.World, player, new List<string>());
                        _clientGui.PrintMenu();
                        switch (playerMenu = _clientGui.ConsoleReadPlayerMenu())
                        {
                            case ConsoleClientGui.PlayerMenu.CycleUnits:
                                CycleUnits(_unitLogic.GetUnfortifiedUnits(player), unitOrders);
                                break;
                            case ConsoleClientGui.PlayerMenu.CycleAllUnits:
                                CycleUnits(_unitLogic.GetAllUnits(player), unitOrders);
                                break;
                            case ConsoleClientGui.PlayerMenu.CycleCities:
                                CycleCities(_cityLogic.GetCitiesWithEmptyBuildQueue(player), cityOrders);
                                break;
                            case ConsoleClientGui.PlayerMenu.CycleAllCities:
                                CycleCities(_cityLogic.GetAllCities(player), cityOrders);
                                break;
                            case ConsoleClientGui.PlayerMenu.EndTurn:
                                if (_cityLogic.GetCitiesWithEmptyBuildQueue(player).Any())
                                {
                                    CycleCities(_cityLogic.GetCitiesWithEmptyBuildQueue(player), cityOrders);
                                }
                                endTurn = true;
                                break;
                        }
                        _api.ExecuteCommands(_namedPipeClientStream, new Actions(unitOrders, cityOrders, endTurn));
                    }
                    while (playerMenu != ConsoleClientGui.PlayerMenu.EndTurn);
                }
            }
        }
    }
}