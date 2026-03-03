"""
Debug version of DQN functions for pyCiv.
Replace these functions in your GlobalDQNetworkSelectingAndMovingMultipleAgents.py file.
"""

import torch
import random
import numpy as np
import os
from ascii_map_display import display_map

def get_valid_select_mask(state):
    """
    Generate a mask indicating valid selections based on the game state.
    Only units with movement points left are considered valid for selection.
    
    Args:
        state: The game state tensor of shape [d, n, m]
        
    Returns:
        torch.Tensor: A flattened mask where 1 indicates valid selections
    """
    # Extract the layers we need
    unit_health_layer = state[1, :, :]  # Shape: [n, m] - Current player's units health
    movement_points_layer = state[2, :, :]  # Shape: [n, m] - Current player's units movement points
    
    # For debugging, print these layers
    print("\nUnit Health Layer:")
    print(unit_health_layer)
    print("\nMovement Points Layer:")
    print(movement_points_layer)
    
    # Generate a mask where positions with movement points > 0 are marked as 1, else 0
    valid_select_mask = (movement_points_layer > 0.01).float()  # Convert boolean mask to float
    
    # Also check that there's a unit there (health > 0)
    unit_present_mask = (unit_health_layer > 0.01).float()
    
    # A valid selection needs both a unit and movement points
    combined_mask = valid_select_mask * unit_present_mask
    
    print("\nValid Selection Mask (2D):")
    print(combined_mask)
    
    # Count valid selections for debugging
    num_valid = combined_mask.sum().item()
    print(f"Number of valid selections: {num_valid}")
    
    # Find coordinates of valid selections
    valid_coords = torch.nonzero(combined_mask)
    if len(valid_coords) > 0:
        print("Valid selection coordinates:")
        for coord in valid_coords:
            i, j = coord
            print(f"  ({i.item()}, {j.item()}) - Health: {unit_health_layer[i, j].item()}, MP: {movement_points_layer[i, j].item()}")
    
    # Flatten the mask to match the shape [n*m], corresponding to flattened select_probs
    flattened_mask = combined_mask.flatten()
    
    return flattened_mask


def select_action(self, state, epsilon=0.1):
    """
    Select an action based on the current state.
    
    Args:
        state: The current state tensor
        epsilon: Exploration rate (probability of choosing a random action)
        
    Returns:
        tuple: (selected_position, move_position) representing the action
    """
    # First, decide whether to explore or exploit
    if random.random() < epsilon:  # Exploration
        print("Selecting random action (exploration)")
        
        # Generate valid selection mask
        original_mask = get_valid_select_mask(state)
        adjusted_mask = adjust_mask_for_end_turn(original_mask)
        valid_positions = torch.where(adjusted_mask > 0)[0].tolist()
        
        if len(valid_positions) > 0:
            # Randomly select a valid position
            selected_pos = random.choice(valid_positions)
            print(f"Randomly selected position {selected_pos}")
            
            # Check if this is the end turn action
            if selected_pos == self.n * self.m:
                print("Selected end turn action")
                # For end turn, the move position doesn't matter
                move_pos = random.randint(0, self.n * self.m - 1)
            else:
                # Get valid moves for the selected position
                valid_moves_mask = get_valid_moves_mask(state, selected_pos)
                valid_moves = torch.where(valid_moves_mask > 0)[0].tolist()
                
                if len(valid_moves) > 0:
                    move_pos = random.choice(valid_moves)
                    print(f"Randomly selected move {move_pos}")
                else:
                    # If no valid moves, choose a random position
                    print("No valid moves found, selecting random move")
                    move_pos = random.randint(0, self.n * self.m - 1)
        else:
            # If no valid positions, default to end turn
            print("No valid selections found, defaulting to end turn")
            selected_pos = self.n * self.m  # End turn action
            move_pos = random.randint(0, self.n * self.m - 1)
        
        return (selected_pos, move_pos)
    
    else:  # Exploitation
        print("Using network to select action (exploitation)")
        # Get network predictions
        with torch.no_grad():
            state_tensor = state.unsqueeze(0)  # Add batch dimension
            
            # Get unit selection probabilities
            select_probs, _ = self.network(state_tensor)
            select_probs = select_probs.squeeze(0)  # Remove batch dimension
            
            # Mask invalid selections
            original_mask = get_valid_select_mask(state)
            select_probs_masked = select_probs * adjust_mask_for_end_turn(original_mask)
            
            # If all selections are invalid (sum is 0), default to end turn
            if select_probs_masked.sum().item() <= 0:
                print("No valid selections according to mask, defaulting to end turn")
                selected_pos = self.n * self.m  # End turn action
                move_pos = random.randint(0, self.n * self.m - 1)
                return (selected_pos, move_pos)
            
            # Normalize masked probabilities
            select_probs_masked = select_probs_masked / select_probs_masked.sum()
            
            # Sample selection position
            selected_pos = torch.multinomial(select_probs_masked, 1).item()
            print(f"Network selected position {selected_pos}")
            
            # Check if this is the end turn action
            if selected_pos == self.n * self.m:
                print("Selected end turn action")
                # For end turn, the move position doesn't matter
                move_pos = random.randint(0, self.n * self.m - 1)
            else:
                # Now get movement probabilities for the selected unit
                _, move_probs = self.network(state_tensor, torch.tensor([[selected_pos]], device=state.device).float())
                move_probs = move_probs.squeeze(0)  # Remove batch dimension
                
                # Mask invalid moves
                valid_moves_mask = get_valid_moves_mask(state, selected_pos)
                move_probs_masked = move_probs * valid_moves_mask
                
                # If all moves are invalid, choose randomly from valid moves
                if move_probs_masked.sum().item() <= 0:
                    print("No valid moves according to mask, selecting random valid move")
                    valid_moves = torch.where(valid_moves_mask > 0)[0].tolist()
                    if valid_moves:
                        move_pos = random.choice(valid_moves)
                    else:
                        move_pos = selected_pos  # Default to staying in place
                else:
                    # Normalize masked probabilities
                    move_probs_masked = move_probs_masked / move_probs_masked.sum()
                    
                    # Sample move position
                    move_pos = torch.multinomial(move_probs_masked, 1).item()
                
                print(f"Network selected move {move_pos}")
        
        return (selected_pos, move_pos)


def build_state_tensor(self, game_env):
    """
    Build a tensor representation of the game state from the raw game environment.
    
    Args:
        game_env: The GameEnvironment instance
        
    Returns:
        torch.Tensor: State tensor representation
    """
    # Initialize a zero tensor with appropriate dimensions
    state_tensor = torch.zeros(self.d, self.n, self.m, device=self.device)
    
    # Get the current player
    current_player = game_env.current_player
    
    print(f"\nBuilding state tensor for {current_player.name}")
    print(f"Player has {len(current_player.units)} units and {len(current_player.cities)} cities")
    
    # Layer 0: Current player's cities
    for city in current_player.cities:
        i, j = city.coordinates
        state_tensor[0, i, j] = 100  # Assuming 100 is the "worth" of a city
        print(f"Added city at ({i}, {j})")
    
    # Layer 1: Current player's units (health)
    # Layer 2: Current player's units (movement points)
    for unit in current_player.units:
        i, j = unit.coordinates
        state_tensor[1, i, j] = unit.health
        state_tensor[2, i, j] = unit.movement_points
        print(f"Added {unit.unit_type} at ({i}, {j}) with health {unit.health} and MP {unit.movement_points}")
    
    # Layers for other players (enemies)
    layer_index = 3
    for player in game_env.players:
        if player == current_player:
            continue  # Skip the current player
        
        print(f"Adding data for enemy {player.name} (has {len(player.units)} units, {len(player.cities)} cities)")
            
        # Enemy cities
        for city in player.cities:
            i, j = city.coordinates
            state_tensor[layer_index, i, j] = -100  # Negative to indicate enemy
            print(f"Added enemy city at ({i}, {j})")
            
        # Enemy units
        for unit in player.units:
            i, j = unit.coordinates
            state_tensor[layer_index + 1, i, j] = -unit.health  # Negative health for enemies
            print(f"Added enemy {unit.unit_type} at ({i}, {j}) with health {unit.health}")
            
        layer_index += 2  # Move to the next pair of layers
    
    # Print some summary statistics about the tensor
    print(f"State tensor shape: {state_tensor.shape}")
    for i in range(self.d):
        layer_sum = state_tensor[i].sum().item()
        print(f"Layer {i} sum: {layer_sum}")
    
    return state_tensor


def train_agents(env, agents, num_episodes=64, batch_size=32, debug=False):
    """
    Train multiple agents with proper state tracking and win counting.
    With added debug prints to diagnose issues.
    
    Args:
        env: The game environment
        agents: List of DQNAgent instances
        num_episodes: Number of training episodes
        batch_size: Batch size for optimization
        debug: Whether to display debug information
    """
    # Initialize win counters for each agent
    win_counts = {i: 0 for i in range(len(agents))}
    win_history = []  # Track winners by episode
    
    for episode in range(num_episodes):
        print(f"Starting episode {episode}")
        # Use the reset method of the environment
        env.reset()
        raw_env_state = env  # The reset method returns the environment itself
        done = False
        
        # Get initial state tensor from the current player's agent
        current_player_index = env.current_player.player_index
        current_agent = agents[current_player_index]
        
        print(f"Initial player: {env.current_player.name}")
        print(f"Player has {len(env.current_player.units)} units with movement points:")
        for unit in env.current_player.units:
            print(f"  {unit.unit_type} at {unit.coordinates}: {unit.movement_points} MP")
        
        next_state = current_agent.build_state_tensor(raw_env_state)
        
        # Initialize a dict to track each agent's last observed state
        last_state_by_agent = {i: next_state for i in range(len(agents))}
        last_action_by_agent = {i: None for i in range(len(agents))}
        
        turn_counter = 0  # To track how many turns have passed
        
        while not done:
            turn_counter += 1
            if turn_counter > 100:  # Safety check to prevent infinite loops
                print("WARNING: Turn limit exceeded, breaking loop")
                break
                
            current_player_index = env.current_player.player_index
            current_agent = agents[current_player_index]
            
            print(f"\n--- Turn {turn_counter}, {env.current_player.name}'s turn ---")
            print(f"Player has {len(env.current_player.units)} units with movement points:")
            for unit in env.current_player.units:
                print(f"  {unit.unit_type} at {unit.coordinates}: {unit.movement_points} MP")
            
            # Get current state from the environment
            state = next_state
            
            # Update this agent's last observed state
            last_state_by_agent[current_player_index] = state
            
            # Get valid selection mask to see what can be selected
            valid_select_mask = get_valid_select_mask(state)
            valid_positions = torch.where(valid_select_mask > 0)[0].tolist()
            print(f"Valid selection positions: {valid_positions}")
            
            # Select an action
            action = current_agent.select_action(state, epsilon=0.3)  # Increase exploration
            last_action_by_agent[current_player_index] = action
            
            print(f"Agent selected action: select={action[0]}, move={action[1]}")
            
            # Convert the action indices to coordinates for the environment
            action_matrix = [
                np.array([action[0] // env.m, action[0] % env.m]), 
                np.array([action[1] // env.m, action[1] % env.m])
            ]
            
            print(f"Converted to coordinates: select={action_matrix[0]}, move={action_matrix[1]}")
            
            # Check if action[0] is the end turn action (n*m index)
            if action[0] == env.n * env.m:
                print("END TURN ACTION SELECTED")
                # End turn action
                env.current_player.end_turn()
                env.next_turn()
                raw_next_env_state = env
                reward = 0  # No immediate reward for ending turn
                done = env.done  # Check if game is done after turn
            else:
                # Take the action in the environment
                try:
                    print(f"Executing step with action_matrix: {action_matrix}")
                    raw_next_env_state, reward, done = env.step(action_matrix)
                    print(f"Step result: reward={reward}, done={done}")
                except AttributeError as e:
                    print(f"AttributeError during step: {e}")
                    # If step method doesn't exist or is incompatible, implement fallback
                    reward = 0
                    
                    # Try to find a unit at the selected position
                    select_row, select_col = action_matrix[0]
                    order_row, order_col = action_matrix[1]
                    
                    # Make sure coordinates are within bounds
                    select_row = select_row % env.n
                    select_col = select_col % env.m
                    order_row = order_row % env.n
                    order_col = order_col % env.m
                    
                    select_pos = (select_row, select_col)
                    order_pos = (order_row, order_col)
                    
                    print(f"Using fallback with select_pos={select_pos}, order_pos={order_pos}")
                    
                    # Get units at the selected position
                    units_at_pos = env.get_units_at(select_pos)
                    
                    # Check if there's a unit belonging to the current player
                    current_player_units = [u for u in units_at_pos if u.player == env.current_player]
                    
                    if current_player_units:
                        # Use the first unit found
                        unit = current_player_units[0]
                        print(f"Found unit: {unit.unit_type} with {unit.movement_points} MP")
                        
                        # If order is the same as selection, fortify
                        if select_pos == order_pos:
                            print(f"Fortifying unit at {select_pos}")
                            unit.fortify()
                        else:
                            # If there's a unit at the order position, try to attack
                            enemy_units = env.get_units_at(order_pos)
                            enemy_units = [u for u in enemy_units if u.player != env.current_player]
                            
                            if enemy_units:
                                # Attack the first enemy unit
                                target = enemy_units[0]
                                print(f"Attacking enemy {target.unit_type} at {order_pos}")
                                damage_dealt, damage_received, target_killed, attacker_killed = unit.attack(target, env)
                                print(f"Attack result: damage_dealt={damage_dealt}, target_killed={target_killed}")
                                
                                if target_killed:
                                    reward += 10  # Reward for killing enemy
                                    
                                if attacker_killed:
                                    reward -= 5  # Penalty for losing unit
                            else:
                                # Try to move
                                print(f"Moving unit from {select_pos} to {order_pos}")
                                moved, final_pos = unit.move(order_pos, env)
                                print(f"Move result: moved={moved}, final_pos={final_pos}")
                                
                                # Check if we captured a city
                                city_at_pos = None
                                for p in env.players:
                                    for c in p.cities:
                                        if c.coordinates == final_pos and p != env.current_player:
                                            city_at_pos = c
                                            break
                                
                                if city_at_pos:
                                    # Capture city
                                    print(f"Captured enemy city at {final_pos}")
                                    city_at_pos.set_owner(env.current_player)
                                    reward += 20  # Reward for capturing city
                    else:
                        print(f"No unit found at selected position {select_pos}")
                    
                    # Go to next player if all units have moved
                    all_units_moved = all(u.movement_points == 0 for u in env.current_player.units)
                    if all_units_moved:
                        print("All units have moved, advancing to next player")
                        env.next_turn()
                    
                    raw_next_env_state = env
                    done = env.done
            
            # Convert raw environment state to tensor for the current agent
            next_state = current_agent.build_state_tensor(raw_next_env_state)
            
            # If it's still this agent's turn, store the transition directly
            if env.current_player.player_index == current_player_index:
                current_agent.store_transition(state, action, reward, next_state, done)
            else:
                # Otherwise, store a pending transition
                current_agent.store_pending_transition(state, action, reward)
            
            # If we're now at a different player's turn, check if that player has pending transitions
            if env.current_player.player_index != current_player_index:
                next_player_index = env.current_player.player_index
                next_player_agent = agents[next_player_index]
                
                # Get the state tensor from the next player's perspective
                next_state = next_player_agent.build_state_tensor(raw_next_env_state)
                
                # Complete any pending transitions for the next player
                if next_player_agent.pending_transitions:
                    next_player_agent.complete_pending_transition(next_state, done)
            
            # Display the map if in debug mode
            if debug:
                display_map(env, debug=True)
            
            # Optimize if enough samples
            if len(current_agent.memory) > batch_size:
                current_agent.optimize(batch_size)
        
        # When episode is done, resolve any remaining pending transitions
        for agent in agents:
            while agent.pending_transitions:
                # For pending transitions at end of game, use last state with done=True
                agent.complete_pending_transition(agent.pending_transitions[0][0], True)
        
        # Determine the winner and update win counts
        winner = determine_winner(env)
        if winner is not None:
            win_counts[winner] += 1
            win_history.append(winner)
        else:
            # If no clear winner (e.g., turn limit reached), record as -1
            win_history.append(-1)
        
        # Print episode summary
        print(f"Episode {episode} completed. Winner: {'None' if winner is None else f'Player {winner+1}'}")
        print(f"Win counts so far: {', '.join([f'Player {i+1}: {count}' for i, count in win_counts.items()])}")
        
        # Save model weights
        for i, agent in enumerate(agents):
            # Create weights directory if it doesn't exist
            if not os.path.exists('weights'):
                os.makedirs('weights')
                
            save_path = f'weights/agent_{i}_episode_{episode}.pth'
            torch.save({
                'model_state_dict': agent.network.state_dict(),
                'optimizer_state_dict': agent.optimizer.state_dict(),
            }, save_path)
    
    # Save win history to file
    save_win_history(win_history, num_episodes)
    
    # Return win statistics
    return win_counts, win_history


def adjust_mask_for_end_turn(original_mask):
    """
    Modify the mask to include the "end turn" action.
    
    Args:
        original_mask: The original selection mask
        
    Returns:
        torch.Tensor: Mask with added end-turn option
    """
    # Get device of the original mask
    device = original_mask.device
    
    # Print the original mask for debugging
    print("\nOriginal mask:")
    print(original_mask)
    print(f"Mask size: {original_mask.size()}")
    print(f"End turn index to append: {original_mask.size(0)}")
    
    # Add a `1` at the end of the original mask to account for the "end turn" action
    end_turn_mask = torch.cat([original_mask, torch.tensor([1.0]).to(device)])
    
    print("\nAdjusted mask with end turn:")
    print(end_turn_mask)
    print(f"New mask size: {end_turn_mask.size()}")
    
    # Calculate probability after normalization
    if end_turn_mask.sum() > 0:
        normalized_mask = end_turn_mask / end_turn_mask.sum()
        print(f"End turn probability: {normalized_mask[-1].item():.4f}")
    else:
        print("Warning: Mask sums to zero!")
    
    return end_turn_mask


def get_valid_moves_mask(state, selected_pos):
    """
    Generate a mask for valid move positions based on the selected unit.
    
    Args:
        state: The game state tensor of shape [d, n, m]
        selected_pos: Index of the selected position in the flattened grid
        
    Returns:
        torch.Tensor: A flattened mask where 1 indicates valid moves
    """
    # Get dimensions from state
    d, n, m = state.shape
    device = state.device
    
    # Convert selected_pos to 2D coordinates
    if selected_pos >= n * m:
        # This is the end turn action, no valid moves
        print(f"End turn selected, returning empty moves mask")
        return torch.zeros(n * m, device=device)
    
    row = selected_pos // m
    col = selected_pos % m
    
    print(f"Getting valid moves for selected position ({row}, {col})")
    
    # Create a mask initially filled with zeros
    valid_move_mask = torch.zeros(n, m, device=device)
    
    # Check if there's a unit at the selected position with movement points
    unit_health = state[1, row, col].item()
    movement_points = state[2, row, col].item()
    
    print(f"Unit at selected position - Health: {unit_health}, MP: {movement_points}")
    
    if unit_health <= 0 or movement_points <= 0:
        print("No valid unit at selected position or no movement points")
        # No unit or no movement points, return empty mask
        return valid_move_mask.flatten()
    
    # Enemy units layer for the first enemy (modify if tracking multiple enemies)
    enemy_units_layer = state[4, :, :]  # Assuming layer 4 is the first enemy's units
    
    # Mark adjacent positions as valid if they're empty or have enemy units
    for dr in [-1, 0, 1]:
        for dc in [-1, 0, 1]:
            # Skip the current position
            if dr == 0 and dc == 0:
                continue
                
            # Calculate new position with wrapping
            new_row = (row + dr) % n
            new_col = (col + dc) % m
            
            # Check if the position is empty or has an enemy unit
            friendly_unit = state[1, new_row, new_col].item() > 0
            enemy_unit = enemy_units_layer[new_row, new_col].item() < 0
            
            if not friendly_unit or enemy_unit:
                valid_move_mask[new_row, new_col] = 1
                print(f"Valid move: ({new_row}, {new_col})")
    
    # Also mark the current position as valid (for fortify action)
    valid_move_mask[row, col] = 1
    print(f"Valid move (fortify): ({row}, {col})")
    
    # Flatten the mask
    flattened_mask = valid_move_mask.flatten()
    
    # Count valid moves for debugging
    num_valid_moves = flattened_mask.sum().item()
    print(f"Total valid moves: {num_valid_moves}")
    
    return flattened_mask