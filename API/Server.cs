using Api.IncomingCommands;
using Api.OutgoingCommands;
using State;
using System;
using System.Collections.Generic;
using System.IO.Pipes;
using System.Threading.Tasks;

namespace Api
{
    public class Server
    {
        private static readonly Server instance = new();

        public static Server GetInstance()
        {
            return instance;
        }

        public NewGame GetNewGame(Connection connection)
        {
            Console.WriteLine("Waiting for client to create new game...");
            while (connection.IsConnected)
            {
                string command = connection.Reader.ReadLine();
                if (!string.IsNullOrEmpty(command))
                {
                    Console.WriteLine("Got a new game from client.");
                    return new NewGame(command);
                }
            }
            return null;
        }

        public Execute GetActions(Connection connection, World world)
        {
            connection.Writer.WriteLine("Process state from server..."); //TODO: What data should be sent?
            while (connection.IsConnected)
            {
                string command = connection.Reader.ReadLine();
                if (!string.IsNullOrEmpty(command))
                {
                    Console.WriteLine("Got commands from client.");
                    return new Execute(command);
                }
            }
            return null;
        }
    }
}
