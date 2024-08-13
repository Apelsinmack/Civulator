import os
import imageio_ffmpeg as ffmpeg
import imageio

plot_directory = 'plots'
save_dir = 'replay_states'

# List all plot files in the directory and sort them
plot_files = sorted([f for f in os.listdir(plot_directory) if f.endswith('.png')])

# Create a video from the saved images
with imageio.get_writer(os.path.join(save_dir, 'game_replay.mp4'), fps=30, format='FFMPEG') as writer:
    for plot_file in plot_files:
        filename = os.path.join(plot_directory, plot_file)
        image = imageio.imread(filename)
        writer.append_data(image)

print(f"Movie created and saved to {os.path.join(save_dir, 'game_replay.mp4')}")
