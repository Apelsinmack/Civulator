import win32pipe
import win32file
import struct

# Open the named pipe for both reading and writing
pipe = win32file.CreateFile(
    r'\\.\pipe\Civulator',
    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
    0, None, win32file.OPEN_EXISTING, 0, None
)

while True:
    # Read the byte stream from the named pipe
    buffer = win32file.ReadFile(pipe, 4096)[1]

    # Deserialize the byte stream into a float array
    float_array_length = struct.unpack('i', buffer[:4])[0]
    float_array_bytes = buffer[4:4 + (float_array_length * 4)]
    float_list = struct.unpack(f'{float_array_length}f', float_array_bytes)

    # Now you can work with the array of floats in Python
    for num in float_list:
        print(num)

    # Data to be sent back through the pipe
    int_to_send = 42

    # Serialize the integer to bytes
    int_bytes = struct.pack('i', int_to_send)

    # Write the data to the named pipe
    win32file.WriteFile(pipe, int_bytes)

# Close the named pipe (This part will not be reached in an infinite loop)
win32file.CloseHandle(pipe)