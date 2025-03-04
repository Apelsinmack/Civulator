def display_map(game_env):
    """
    Creates an ASCII representation of the current game state.
    
    Args:
        game_env: The GameEnvironment instance
    """
    # Create a grid representation filled with empty spaces
    grid = [[' . ' for _ in range(game_env.m)] for _ in range(game_env.n)]
    
    # Fill in the cities
    for player in game_env.players:
        for city in player.cities:
            i, j = city.coordinates
            grid[i][j] = f'C{player.player_index+1}'
    
    # Fill in the units
    for player in game_env.players:
        for unit in player.units:
            i, j = unit.coordinates
            # Add health in parentheses and indicate if unit has movement points
            movement_indicator = '*' if unit.movement_points > 0 else ' '
            if grid[i][j].startswith('C'):  # If there's a city here
                grid[i][j] = f'{grid[i][j]}{movement_indicator}{unit.unit_type[0]}({int(unit.health)})'
            else:
                grid[i][j] = f'{player.player_index+1}{movement_indicator}{unit.unit_type[0]}({int(unit.health)})'
    
    # Print the current turn and player
    print(f"\nTurn {game_env.turn_counter}, {game_env.current_player.name}'s turn")
    
    # Print column headers
    print('   ' + ''.join([f' {j:2} ' for j in range(game_env.m)]))
    
    # Print the grid with row numbers
    for i in range(game_env.n):
        row_str = f'{i:2} |'
        for j in range(game_env.m):
            row_str += f'{grid[i][j]:^4}|'
        print(row_str)
    
    # Print player stats
    print("\nPlayer Stats:")
    for player in game_env.players:
        unit_count = len(player.units)
        city_count = len(player.cities)
        status = "DEAD" if player.is_dead else "ALIVE"
        print(f"{player.name}: {unit_count} units, {city_count} cities, Status: {status}")

# Add this to your game loop to visualize after each step
# For example, in the training loop:
"""
while not done: 
    current_player_index = env.current_player.player_index
    current_agent = agents[current_player_index]
    state = next_state
    action = current_agent.select_action(state)
    action_matrix = [np.array([action[0] // m, action[0] % m]), np.array([action[1] // m, action[1] % m])]
    
    next_state, reward, done = env.step(action_matrix)
    current_agent.store_transition(state, action, reward, next_state, done)
    
    # Add visualization here
    display_map(env)
    
    if len(current_agent.memory) > BATCH_SIZE:
        current_agent.optimize(BATCH_SIZE)
"""
