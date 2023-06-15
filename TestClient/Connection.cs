using System;
using System.Collections.Generic;
using System.IO.Pipes;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace TestClient
{
    public class Connection
    {
        public StreamReader Reader { get; }
        public StreamWriter Writer { get; }
        public bool IsConnected { get; }

        public Connection(NamedPipeClientStream pipeClient)
        {
            Reader = new StreamReader(pipeClient);
            Writer = new StreamWriter(pipeClient) { AutoFlush = true };
            IsConnected = pipeClient.IsConnected;
        }
    }
}
