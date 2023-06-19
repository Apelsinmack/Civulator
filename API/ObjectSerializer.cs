using System;
using System.IO;
using System.Runtime.Serialization.Formatters.Binary;

public static class ObjectSerializer
{
    public static byte[] Serialize(object obj)
    {
        BinaryFormatter formatter = new BinaryFormatter();
        using (MemoryStream memoryStream = new MemoryStream())
        {
            formatter.Serialize(memoryStream, obj);
            return memoryStream.ToArray();
        }
    }

    public static T Deserialize<T>(byte[] data)
    {
        BinaryFormatter formatter = new BinaryFormatter();
        using (MemoryStream memoryStream = new MemoryStream(data))
        {
            object obj = formatter.Deserialize(memoryStream);
            if (obj is T result)
            {
                return result;
            }
            else
            {
                throw new InvalidCastException($"Unable to cast deserialized object to type '{typeof(T).FullName}'.");
            }
        }
    }
}