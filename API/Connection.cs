using System;
using System.Collections.Generic;
using System.IO.Pipes;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Api
{
    public class Connection
    {
        public StreamReader Reader { get; }
        public StreamWriter Writer { get; }
        public bool IsConnected { get; }

        public Connection(NamedPipeServerStream pipeServer)
        {
            Reader = new StreamReader(pipeServer);
            Writer = new StreamWriter(pipeServer) { AutoFlush= true };
            IsConnected = pipeServer.IsConnected;
        }
    }
}
