using Api.IncomingCommands;
using Api;
using State;
using State.Factories;
using System;
using System.Collections.Generic;
using System.Data.Common;
using System.IO.Pipes;
using System.Threading.Tasks;

namespace TestClient
{
    public class Client
    {
        private readonly Api _api;
        private Connection _connection;

        public Client()
        {
            _api = Api.GetInstance();
        }

        public void Start()
        {
            using (var pipeClient = new NamedPipeClientStream(".", "Civ", PipeDirection.InOut))
            {
                Console.WriteLine("Connecting to server...");
                pipeClient.Connect();
                Console.WriteLine("Connected to server.");
                _connection = new Connection(pipeClient);
                _api.GenerateWorld(_connection);
                while (true)
                {
                    _api.ExecuteCommands(_connection);
                }
            }
        }
    }
}