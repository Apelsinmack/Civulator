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
                _api.GenerateWorld(namedPipeClientStream);
                while (namedPipeClientStream.IsConnected)
                {
                    NewState newState = _api.GetState(namedPipeClientStream);
                    if(newState.World.Victory.Player != null)
                    {
                        Console.WriteLine($"Congratulations to the victory {newState.World.Victory.Player.Name}!");
                        Console.ReadLine();
                        return;
                    }
                    Player currentPlayer = PlayerLogic.GetCurrentPlayer(newState.World);
                    IEnumerable<Unit> units = newState.World.Map.Tiles.SelectMany(tile => tile.Value.Units).Where(unit => unit.Owner.Id == currentPlayer.Id);
                    List<UnitOrder> unitOrders = new();
                    foreach (var unit in units)
                    {
                        if (unit.MovementLeft > 0)
                        {
                            Console.WriteLine($"Move {unit.Class.ToString()}");
                            unitOrders.Add(new UnitOrder(ConsoleReadUnitOrder(), unit));
                        }
                    }
                    bool endTurn = unitOrders.Count == 0;
                    //Console.WriteLine("End turn?");
                    //bool endTurn = Console.ReadLine() == "y";
                    _api.ExecuteCommands(namedPipeClientStream, new Actions(unitOrders, endTurn));
                }
            }
        }
    }
}