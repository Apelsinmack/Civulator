﻿using Api.IncomingCommands;
using Api.OutgoingCommands;
using State;
using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace Api
{
    public class Server
    {
        private static readonly Server _instance = new();

        private T ReadData<T>(NamedPipeServerStream namedPipeServerStream)
        {
            using (MemoryStream memoryStream = new MemoryStream())
            {
                byte[] lengthBuffer = new byte[4];
                int bytesRead;

                namedPipeServerStream.Read(lengthBuffer, 0, lengthBuffer.Length);
                int messageLength = BitConverter.ToInt32(lengthBuffer, 0);

                byte[] dataBuffer = new byte[4096];
                while (messageLength > 0 && (bytesRead = namedPipeServerStream.Read(dataBuffer, 0, Math.Min(dataBuffer.Length, messageLength))) > 0)
                {
                    memoryStream.Write(dataBuffer, 0, bytesRead);
                    messageLength -= bytesRead;
                }

                byte[] dataBytes = memoryStream.ToArray();
                return JsonSerializer.Deserialize<T>(dataBytes);
            }
        }

        private void WriteData<T>(NamedPipeServerStream namedPipeServerStream, T dataObject)
        {
            byte[] dataBytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(dataObject));
            byte[] lengthBytes = BitConverter.GetBytes(dataBytes.Length);
            namedPipeServerStream.Write(lengthBytes, 0, lengthBytes.Length);
            namedPipeServerStream.Write(dataBytes, 0, dataBytes.Length);
            namedPipeServerStream.Flush();
        }

        private Server() { }

        public static Server GetInstance()
        {
            return _instance;
        }

        public NewGame GetNewGame(NamedPipeServerStream namedPipeServerStream)
        {
            while (namedPipeServerStream.IsConnected)
            {
                return ReadData<NewGame>(namedPipeServerStream);
            }
            return null;
        }

        public Actions GetHumanActions(NamedPipeServerStream namedPipeServerStream, World world)
        {
            WriteData(namedPipeServerStream, new GameState(world));
            while (namedPipeServerStream.IsConnected)
            {
                return ReadData<Actions>(namedPipeServerStream);
            }
            return null;
        }

        public Actions GetAIActions(NamedPipeServerStream namedPipeServerStream, World world)
        {
            var unitTileIndexes = world.Units.Select(unit => unit.Value.TileIndex).ToArray();

            using (MemoryStream memoryStream = new MemoryStream())
            {
                using (BinaryWriter writer = new BinaryWriter(memoryStream))
                {
                    writer.Write(unitTileIndexes.Length);
                    foreach (int unitTileIndex in unitTileIndexes)
                    {
                        writer.Write(unitTileIndex);
                    }
                }

                byte[] byteArray = memoryStream.ToArray();

                namedPipeServerStream.Write(byteArray, 0, byteArray.Length);
            }

            while (namedPipeServerStream.IsConnected)
            {
                using (MemoryStream memoryStream = new MemoryStream())
                {
                    byte[] lengthBuffer = new byte[4];
                    int bytesRead;

                    namedPipeServerStream.Read(lengthBuffer, 0, lengthBuffer.Length);
                    int messageLength = BitConverter.ToInt32(lengthBuffer, 0);

                    //byte[] dataBuffer = new byte[4096];
                    //while (messageLength > 0 && (bytesRead = namedPipeServerStream.Read(dataBuffer, 0, Math.Min(dataBuffer.Length, messageLength))) > 0)
                    //{
                    //    memoryStream.Write(dataBuffer, 0, bytesRead);
                    //    messageLength -= bytesRead;
                    //}

                    //byte[] dataBytes = memoryStream.ToArray();
                    return new Actions(new List<UnitOrder>(), new List<CityOrder>(), true);
                }
            }
            return null;
        }

        public void SendState(NamedPipeServerStream namedPipeServerStream, World world)
        {
            WriteData(namedPipeServerStream, new GameState(world));
        }
    }
}
