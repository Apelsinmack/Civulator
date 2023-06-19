using Api.IncomingCommands;
using Api;
using State;
using State.Factories;
using System;
using System.Collections.Generic;
using System.Data.Common;
using System.IO.Pipes;
using System.Threading.Tasks;
using Api.IncomingCommands.Actions.Enums;
using Api.OutgoingCommands;
using Api.IncomingCommands.Actions;

namespace TestClient
{
    public class Client
    {
        private readonly Api _api;

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

        public Client()
        {
            _api = Api.GetInstance();
        }

        public void Start()
        {
            using (var namedPipeClientStream = new NamedPipeClientStream(".", "Civulator", PipeDirection.InOut))
            {
                Console.WriteLine("Connecting to server...");
                namedPipeClientStream.Connect();
                Console.WriteLine("Connected to server.");
                _api.GenerateWorld(namedPipeClientStream);
                while (namedPipeClientStream.IsConnected)
                {
                    NewState newState = _api.GetState(namedPipeClientStream);
                    int currentTurn = newState.World.Players.Min(Player => Player.Turn);
                    Player currentPlayer = newState.World.Players.Find(player => player.Turn == currentTurn);
                    List<Unit> units = newState.World.Map.Tiles.SelectMany(tile => tile.Value.Units).Where(unit => unit.Owner.Id == currentPlayer.Id).ToList();
                    List<UnitOrder> unitOrders = new();
                    units.ForEach(unit =>
                    {
                        Console.WriteLine($"Move {unit.Type.ToString()}");
                        unitOrders.Add(new UnitOrder(ConsoleReadUnitOrder(), unit));
                    });
                    Console.WriteLine("End turn?");
                    bool endTurn = Console.ReadLine() == "y";
                    _api.ExecuteCommands(namedPipeClientStream, new Execute(unitOrders, endTurn));
                }
            }
        }
    }
}