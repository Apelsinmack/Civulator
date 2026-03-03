using Api;
using Game;
using System.IO.Pipes;

//Server server = Server.GetInstance();
//float[] floatArray = { 1.23f, 4.56f, 7.89f };

//using (MemoryStream memoryStream = new MemoryStream())
//{
//    using (BinaryWriter writer = new BinaryWriter(memoryStream))
//    {
//        writer.Write(floatArray.Length);
//        foreach (float num in floatArray)
//        {
//            writer.Write(num);
//        }
//    }

//    // Get the byte array from the memory stream
//    byte[] byteArray = memoryStream.ToArray();

//    // Create a named pipe server
//    using (NamedPipeServerStream pipeServer = new NamedPipeServerStream("Civulator", PipeDirection.InOut, 99))
//    {
//        Console.WriteLine("Waiting for connection...");
//        pipeServer.WaitForConnection();
//        Console.WriteLine("Client connected.");

//        // Write the byte array to the named pipe
//        pipeServer.Write(byteArray, 0, byteArray.Length);
//    }
//}

Engine engine = new Engine();
engine.Start();