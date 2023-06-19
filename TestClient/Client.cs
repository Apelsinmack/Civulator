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
                while (true)
                {
                    _api.ExecuteCommands(namedPipeClientStream);
                }
            }
        }
    }
}