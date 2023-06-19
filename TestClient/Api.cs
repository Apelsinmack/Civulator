using Api.IncomingCommands;
using Api.IncomingCommands.Actions;
using Api.IncomingCommands.Actions.Enums;
using Api.OutgoingCommands;
using State;
using System;
using System.Collections.Generic;
using System.IO.Pipes;
using System.Text.Json;
using System.Text;
using System.Threading.Tasks;

namespace TestClient
{
    public class Api
    {
        private static readonly Api instance = new Api();

        public static Api GetInstance()
        {
            return instance;
        }

        private T ReadData<T>(NamedPipeClientStream namedPipeClientStream)
        {
            Console.WriteLine($"Get {typeof(T).FullName}...");
            using (MemoryStream memoryStream = new MemoryStream())
            {
                byte[] lengthBuffer = new byte[4];
                int bytesRead;

                namedPipeClientStream.Read(lengthBuffer, 0, lengthBuffer.Length);
                int messageLength = BitConverter.ToInt32(lengthBuffer, 0);

                byte[] dataBuffer = new byte[4096];
                while (messageLength > 0 && (bytesRead = namedPipeClientStream.Read(dataBuffer, 0, Math.Min(dataBuffer.Length, messageLength))) > 0)
                {
                    memoryStream.Write(dataBuffer, 0, bytesRead);
                    messageLength -= bytesRead;
                }

                byte[] dataBytes = memoryStream.ToArray();
                return JsonSerializer.Deserialize<T>(dataBytes);
            }
        }

        private void WriteData<T>(NamedPipeClientStream namedPipeClientStream, T dataObject)
        {
            Console.WriteLine($"Send {typeof(T).FullName}...");
            byte[] dataBytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(dataObject));
            byte[] lengthBytes = BitConverter.GetBytes(dataBytes.Length);
            namedPipeClientStream.Write(lengthBytes, 0, lengthBytes.Length);
            namedPipeClientStream.Write(dataBytes, 0, dataBytes.Length);
            namedPipeClientStream.Flush();
        }

        public void GenerateWorld(NamedPipeClientStream namedPipeClientStream)
        {
            while (namedPipeClientStream.IsConnected)
            {
                List<Player> players = new()
                {
                    new Player("Megadick", true, new Leader(ConsoleColor.Red)),
                    new Player("Ken Q", true, new Leader(ConsoleColor.Blue))
                };

                WriteData(namedPipeClientStream, new NewGame(40, 20, players));
                break;
            }
        }

        public Execute ExecuteCommands(NamedPipeClientStream namedPipeClientStream)
        {
            while (namedPipeClientStream.IsConnected)
            {
                Console.WriteLine("Waiting for next turn...");
                NewState newState = ReadData<NewState>(namedPipeClientStream);
                Console.WriteLine("Processing important data...");
                Console.WriteLine("End turn?");
                bool endTurn = Console.ReadLine() == "y";
                List<BaseAction> actions = new()
                {
                    new UnitOrder(UnitOrderType.Up),
                    new UnitOrder(UnitOrderType.Down)
                };
                WriteData(namedPipeClientStream, new Execute(actions, endTurn));
                Console.WriteLine("------------------------------");
            }
            return null;
        }
    }
}