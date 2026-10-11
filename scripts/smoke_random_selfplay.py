"""Seeded random-policy self-play smoke run (issue #87 P4 gate).

Both seats play uniformly random VALID actions (DQNAgent epsilon=1.0 draws from
the real action masks), cities pick a random build option when idle. Logs, at
round checkpoints, tiles owned per player, total population, cumulative
culture claims, per-player housing vs population and growth_slowed_turns, plus wall-clock. A sanity check that borders grow in real games,
not a measurement.

Usage: python scripts/smoke_random_selfplay.py [--seed 4242] [--rounds 250]
"""

import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import torch

from civulator.agents import DQNAgent, ReplayMemory, get_encoder
from civulator.agents.action_space import decode_action, end_turn_index
from civulator.agents.build_agent import BUILD_OPTIONS
from civulator.game.city import City
from civulator.game.housing import housing
from civulator.game import GameEnvironment, resolve_size_and_players

STEP_LIMIT = 200_000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--rounds", type=int, default=250)
    parser.add_argument("--size", default="duel")
    parser.add_argument("--every", type=int, default=50)
    args = parser.parse_args()

    n, m, num_players = resolve_size_and_players(size=args.size)
    env = GameEnvironment(n, m, num_players)
    env.max_turns = args.rounds
    env.reset(seed=args.seed)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    d = get_encoder("basic").get_depth(num_players)
    agent = DQNAgent(n, m, d, ReplayMemory(1), encoder="basic", fully_conv=True)
    end_idx = end_turn_index(n, m)

    def log(round_no):
        owned = [env.map.owned_tile_count(i) for i in range(num_players)]
        pop = sum(c.population for p in env.players for c in p.cities)
        cities = [len(p.cities) for p in env.players]
        claims = sum(s["tiles_claimed_by_culture"] for s in env.episode_stats.values())
        # Per player: total housing (whole units) vs total population, and
        # city-turns where growth was slowed by housing (issue #88).
        house = [sum(housing(c) for c in p.cities) // 10 for p in env.players]
        pops = [sum(c.population for c in p.cities) for p in env.players]
        slowed = [env.episode_stats[i]["growth_slowed_turns"] for i in range(num_players)]
        print(f"round {round_no:4d}  tiles_owned={owned}  cities={cities}  "
              f"population={pop}  culture_claims={claims}  housing={house}  "
              f"pop_by_player={pops}  growth_slowed_turns={slowed}  "
              f"t={time.perf_counter() - t0:.1f}s")

    t0 = time.perf_counter()
    log(0)
    next_log = args.every
    last_player = -1
    steps = 0
    while not env.done and steps < STEP_LIMIT:
        steps += 1
        if env.current_player.player_index != last_player:
            for city in env.current_player.cities:
                if city.current_production is None:
                    option = random.choice(BUILD_OPTIONS)
                    if option in City.BUILDING_COSTS:
                        city.produce_building(option)
                    else:
                        city.produce_unit(option)
            last_player = env.current_player.player_index
        state = agent.build_state_tensor(env)
        selected, move = agent.select_action(state, epsilon=1.0, game_env=env)
        if selected == end_idx:
            env.current_player.end_turn()
            env.next_turn()
        else:
            env.step(decode_action(selected, move, n, m))
        while next_log <= args.rounds and env.turn_counter > next_log:
            log(next_log)
            next_log += args.every
    log(env.turn_counter)
    print(f"done={env.done} steps={steps} wall={time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
