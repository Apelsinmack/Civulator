import torch
import numpy as np
import matplotlib.pyplot as plt
import pyCiv
from training_agent import DQNAgent, SelectAndMoveNetwork, ReplayMemory
import os

def load_weights_for_evaluation(weights_path, agent):
    if os.path.exists(weights_path):
        checkpoint = torch.load(weights_path)
        agent.network.load_state_dict(checkpoint['model_state_dict'])
        print(f"Loaded weights from {weights_path} for evaluation.")
    else:
        print("Weights file not found, please check the path.")
        return False  # Indicate failure to load weights
    return True  # Indicate successful loading of weights

def evaluate_agent(env, agent, num_games):
    results = []
    max_turns = 100
    for _ in range(num_games):
        state = env.reset(2)
        game_states = [state]  # List to store states for visualization
        actions_taken = []  # List to store actions for visualization
        done = False
        while not done:
            
            action = agent.select_action(state, eval_mode=True)
            actions_taken.append(action)
            action_matrix = [np.array([action[0] // env.m, action[0] % env.n]), np.array([action[0] // env.m, action[1] % env.n])]
            state, reward, done = env.step(action_matrix)
            if env.turn_counter >= max_turns:
                done=True
            game_states.append(state)
            
        results.append((game_states, actions_taken))  # Store games' states and actions
    return results

def plot_game(game_states, actions_taken, save_dir='game_plots'):
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)  # Create directory if it does not exist

    for i, state in enumerate(game_states):
        fig, ax = plt.subplots()
        if state.shape[0] == 3:  # Check if it is an RGB image
            ax.imshow(state[1:-1].permute(1, 2, 0))  # Correcting tensor shape for RGB image
        else:
            ax.imshow(state[1:-1].permute(1, 2, 0), cmap='hot')  # Use squeeze in case it's a 1-channel image
        # ax.set_title(f"Action: {actions_taken[i]}")
        # Save the figure
        plt.savefig(os.path.join(save_dir, f'game_frame_{i}.png'))  # Save each frame as a PNG file
        plt.close(fig)  # Close the plot to free up memory
def main():
    env = pyCiv.GameEnvironment(n=5, m=6, number_of_players=2)
    agent = DQNAgent(n=5, m=6, d=5, memory=ReplayMemory(10000))
    weights_path = os.getcwd() + '\\weights\\model_episode_1.pth'
    if load_weights_for_evaluation(weights_path, agent):
        eval_results = evaluate_agent(env, agent, num_games=1)
        for game_states, actions_taken in eval_results:
            plot_game(game_states, actions_taken)

if __name__ == "__main__":
    main()
