def display_map(game_env, debug=False):
    """
    Creates an ASCII representation of the current game state with hexagonal layout.
    
    Args:
        game_env: The GameEnvironment instance
        debug: Boolean flag to enable/disable display (default: False)
    
    Returns:
        None: Just prints to console if debug is True
    """
    # Don't display anything if debug mode is off
    if not debug:
        return
    
    # Create a grid representation filled with empty spaces
    grid = [["   " for _ in range(game_env.m)] for _ in range(game_env.n)]
    
    # Fill in the cities
    for player in game_env.players:
        for city in player.cities:
            i, j = city.coordinates
            grid[i][j] = f"C{player.player_index+1} "
    
    # Fill in the units
    for player in game_env.players:
        for unit in player.units:
            i, j = unit.coordinates
            # First character: unit type
            unit_char = unit.unit_type[0]
            # Second character: player index
            player_char = str(player.player_index+1)
            # Third character: movement indicator
            movement_char = "*" if unit.movement_points > 0 else " "
            
            # Overwrite default tile, preserving city info if needed
            if grid[i][j].startswith("C"):
                # If there's a city here, keep the city info and add unit health separately
                grid[i][j] = f"C{player_char}{movement_char}"
                # Print health separately, perhaps near player stats
            else:
                grid[i][j] = f"{unit_char}{player_char}{movement_char}"
    
    # Print the current turn and player
    print(f"\nTurn {game_env.turn_counter}, {game_env.current_player.name}'s turn")
    
    # Print column headers with proper offset
    header_row = "   "
    for j in range(game_env.m):
        header_row += f" {j:2}"
    print(header_row)
    
    # Print the grid with row numbers and hexagonal offset
    for i in range(game_env.n):
        # Calculate offset for this row to create hexagonal appearance
        offset = " " * ((game_env.n - 1 - i) * 2)
        row_str = f"{i:2} |{offset}"
        
        for j in range(game_env.m):
            row_str += f"{grid[i][j]}|"
        print(row_str)
    
    # Print unit health information
    print("\nUnit Health:")
    for player in game_env.players:
        for unit in player.units:
            i, j = unit.coordinates
            print(f"{player.name} {unit.unit_type} at ({i},{j}): {int(unit.health)} HP")
    
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
    display_map(env, debug=True)
    
    if len(current_agent.memory) > BATCH_SIZE:
        current_agent.optimize(BATCH_SIZE)
"""