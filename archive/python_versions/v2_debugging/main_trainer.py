"""
Main training script for pyCiv DQN agent
"""
import os
import torch
import random
import numpy as np
from collections import namedtuple



# Import other required modules
import pyCiv
from ascii_map_display import display_map
from GlobalDQNetworkSelectingAndMovingMultipleAgents import (
    DQNAgent, ReplayMemory, train_agents, 
    SelectAndMoveNetwork, determine_winner
)

def set_random_seeds(seed=42):
    """Set random seeds for reproducibility."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        
def main(resume_training=False, checkpoint_episode=None):
    """
    Main training function that handles new training or resuming from a checkpoint.
    
    Args:
        resume_training (bool): Whether to resume from previous training
        checkpoint_episode (int): Episode number to resume from (if None, uses latest)
    """
    # Set random seeds for reproducibility
    set_random_seeds()
    

    
    # Environment and agent setup
    n, m = 4, 8  # Grid size
    number_of_players = 2
    d = 2 * number_of_players + 1  # State tensor depth
    
    # Create the game environment
    env = pyCiv.GameEnvironment(n, m, number_of_players)
    
    # Create memory for each agent
    memories = [ReplayMemory(10000) for _ in range(number_of_players)]
    
    # Create agents with different learning rates
    agents = [
        DQNAgent(n, m, d, memories[0], learning_rate=0.001),
        DQNAgent(n, m, d, memories[1], learning_rate=0.001),
    ]
    
    # Add a third agent if we have 3 players
    if number_of_players > 2:
        memories.append(ReplayMemory(10000))
        agents.append(DQNAgent(n, m, d, memories[2], learning_rate=0.001))
    
    # Load checkpoints if resuming training
    if resume_training:
        # Determine checkpoint paths
        if checkpoint_episode is not None:
            checkpoint_paths = [f'weights/agent_{i}_episode_{checkpoint_episode}.pth' 
                              for i in range(number_of_players)]
        else:
            # Find latest episode checkpoint
            weight_files = os.listdir('weights') if os.path.exists('weights') else []
            episodes = []
            for file in weight_files:
                match = re.match(r'agent_0_episode_(\d+)\.pth', file)
                if match:
                    episodes.append(int(match.group(1)))
            
            if episodes:
                latest_episode = max(episodes)
                print(f"Found latest checkpoint at episode {latest_episode}")
                checkpoint_paths = [f'weights/agent_{i}_episode_{latest_episode}.pth'
                                 for i in range(number_of_players)]
            else:
                print("No checkpoints found. Starting with fresh weights.")
                resume_training = False
        
        # Load checkpoints
        if resume_training:
            for i, agent in enumerate(agents):
                try:
                    checkpoint = torch.load(checkpoint_paths[i])
                    agent.network.load_state_dict(checkpoint['model_state_dict'])
                    agent.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
                    print(f"Successfully loaded checkpoint for Agent {i}")
                except Exception as e:
                    print(f"Failed to load checkpoint for Agent {i}: {e}")
                    print("Starting with fresh weights for this agent.")
    
    # Train agents
    win_counts, win_history = train_agents(env, agents, num_episodes=64, batch_size=32, debug=True)
    
    # Print final results
    print("\nTraining complete!")
    print("Final win counts:")
    for i, count in win_counts.items():
        print(f"Player {i+1}: {count} wins")
    
    return win_counts, win_history

if __name__ == "__main__":
    import argparse
    import re
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Train agents for Civilization-like game')
    parser.add_argument('--resume', action='store_true', help='Resume training from checkpoint')
    parser.add_argument('--episode', type=int, help='Specific episode checkpoint to load')
    parser.add_argument('--episodes', type=int, default=64, help='Number of episodes to train')
    parser.add_argument('--batch-size', type=int, default=32, help='Batch size for training')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    args = parser.parse_args()
    
    # Run main function with parsed arguments
    main(resume_training=args.resume, checkpoint_episode=args.episode)