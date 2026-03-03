"""ASCII map display for debugging the game state."""


def display_map(game_env, debug=False):
    """Print an ASCII hex map of the current game state.

    Args:
        game_env: The GameEnvironment instance
        debug: Only displays if True
    """
    if not debug:
        return

    grid = [["   " for _ in range(game_env.m)] for _ in range(game_env.n)]

    # Fill in cities
    for player in game_env.players:
        for city in player.cities:
            i, j = city.coordinates
            grid[i][j] = f"C{player.player_index+1} "

    # Fill in units
    for player in game_env.players:
        for unit in player.units:
            i, j = unit.coordinates
            unit_char = unit.unit_type[0]
            player_char = str(player.player_index + 1)
            movement_char = "*" if unit.movement_points > 0 else " "

            if grid[i][j].startswith("C"):
                grid[i][j] = f"C{player_char}{movement_char}"
            else:
                grid[i][j] = f"{unit_char}{player_char}{movement_char}"

    print(f"\nTurn {game_env.turn_counter}, {game_env.current_player.name}'s turn")

    # Column headers
    header_row = "   "
    for j in range(game_env.m):
        header_row += f" {j:2}"
    print(header_row)

    # Grid rows with hex offset
    for i in range(game_env.n):
        offset = " " * ((game_env.n - 1 - i) * 2)
        row_str = f"{i:2} |{offset}"
        for j in range(game_env.m):
            row_str += f"{grid[i][j]}|"
        print(row_str)

    # Unit health
    print("\nUnit Health:")
    for player in game_env.players:
        for unit in player.units:
            i, j = unit.coordinates
            print(f"  {player.name} {unit.unit_type} at ({i},{j}): {int(unit.health)} HP")

    # Player stats
    print("\nPlayer Stats:")
    for player in game_env.players:
        status = "DEAD" if player.is_dead else "ALIVE"
        print(
            f"  {player.name}: {len(player.units)} units, "
            f"{len(player.cities)} cities, {status}"
        )
