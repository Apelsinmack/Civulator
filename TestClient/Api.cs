using Api.IncomingCommands;
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

        public NewState GetState(NamedPipeClientStream namedPipeClientStream)
        {
            while (namedPipeClientStream.IsConnected)
            {
                return ReadData<NewState>(namedPipeClientStream);
            }
            return null;
        }

        public void ExecuteCommands(NamedPipeClientStream namedPipeClientStream, Actions execute)
        {
            while (namedPipeClientStream.IsConnected)
            {
                WriteData(namedPipeClientStream, execute);
                break;
            }
        }
    }
}