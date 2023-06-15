using Api.IncomingCommands;
using Api.IncomingCommands.Actions;
using Api.IncomingCommands.Actions.Enums;
using Api.OutgoingCommands;
using State;
using System;
using System.Collections.Generic;
using System.IO.Pipes;
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

        public void GenerateWorld(Connection connection)
        {
            while (connection.IsConnected)
            {
                List<Player> players = new()
                {
                    new Player("Megadick", true, new Leader(ConsoleColor.Red)),
                    new Player("Ken Q", true, new Leader(ConsoleColor.Blue))
                };
                connection.Writer.WriteLine(new NewGame(40, 20, players).Serialize());
                break;
            }
        }

        public Execute ExecuteCommands(Connection connection)
        {
            while (connection.IsConnected)
            {
                Console.WriteLine("Waiting for next turn...");
                string importantData = connection.Reader.ReadLine();
                Console.WriteLine(importantData);
                Console.WriteLine("End turn?");
                bool endTurn = Console.ReadLine() == "y";
                //List<IAction> actions = new()
                //{
                //    new UnitOrder(UnitOrderType.Up),
                //    new UnitOrder(UnitOrderType.Down)
                //};
                List<string> actions = new()
                {
                    "Action 1",
                    "Action 2"
                };
                connection.Writer.WriteLine(new Execute(actions, endTurn).Serialize());
                Console.WriteLine("------------------------------");
            }
            return null;
        }
    }
}