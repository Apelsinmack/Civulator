import win32pipe, win32file
import struct

pipe = win32file.CreateFile(r'\\.\pipe\my_pipe3',
                            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                            0, None, win32file.OPEN_EXISTING, 0, None)

# Read the byte stream from the named pipe
buffer = win32file.ReadFile(pipe, 4096)[1]

# Deserialize the byte stream into a float array
float_array_length = struct.unpack('i', buffer[:4])[0]
float_array_bytes = buffer[4:4 + (float_array_length * 4)]
float_list = struct.unpack(f'{float_array_length}f', float_array_bytes)

# Now you can work with the array of floats in Python
for num in float_list:
    print(num)

# Close the named pipe
win32file.CloseHandle(pipe)