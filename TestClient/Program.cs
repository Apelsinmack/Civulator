using TestClient;

Client client = new Client();
client.Start();


//using Api;
//using State;
//using System.Reflection.PortableExecutable;

//Client client = new Client();
//List<Player> players = new()
//{
//    new Player("Megadick", true, new Leader(ConsoleColor.Red)),
//    new Player("Ken Q", true, new Leader(ConsoleColor.Blue))
//};
//client.NewGame(40, 20, players);

//while (true)
//{
//    foreach (var player in players)
//    {
//        Console.WriteLine("Player: " + player.Name);
//        client.NextPlayer();
//        Console.WriteLine("ENTER");
//        Console.ReadLine();
//        client.Actions();
//    }
//}
