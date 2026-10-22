"""Seeded random-policy self-play smoke run (issue #87 P4 gate).

Both seats play uniformly random VALID actions (DQNAgent epsilon=1.0 draws from
the real action masks), cities pick a random build option when idle -- drawn
from `get_valid_build_mask`, so only what the city may build (#116 P2: the
tech gates; never `random.choice(BUILD_OPTIONS)`). Logs, at
round checkpoints, tiles owned per player, total population, cumulative
culture claims, per-player housing vs population and growth_slowed_turns,
techs researched per player (the engine's research default, #116 P2), civics
researched, the government and the slotted policy cards per player (the
engine's civic, government and loadout defaults, #116 P4), and per player the
treasury (whole gold), the upkeep paid, the units disbanded by bankruptcy,
the trade routes opened and running (the engine's Trader default) and the
gold and faith spent on purchases (#116 P5; 0: no default buys), and
per player the lowest and the mean loyalty of its cities and the cities it
lost and gained by loyalty flips (#116 P7; the end line adds the lowest
loyalty any of its cities had after any round), and per player the
improvements its Workers built, the improvements standing on its tiles and its
Workers alive (#116 P8; the engine's Worker default builds them -- nothing
here orders a Worker's work, though the random agent may move one), and
the verdict (#116 P9: the winner and how the game ended, with each player's
score term by term), plus wall-clock. A sanity check that borders grow, research and civics progress,
the defaults adopt governments, slot cards, send Traders and improve tiles,
upkeep is paid and loyalty moves in real games, not a measurement.

Districts (#86) and wonders (#116 P6, district-registry entries of kind
"wonder"): at each player's turn start every city has a small chance to
place one through the engine (the type drawn from a seeded RNG over the
config-ordered types its owner `player_can_build`, the tile from
Map.tiles_of_city, sorted, filtered by can_place_district -- which also
refuses a wonder any player completed) and idle cities finish their placed
districts and wonders. The end line reports districts placed / completed,
the Aqueduct housing seen, and per player the wonders completed, the wonder
races lost and the complete wonders held at the end.

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
from civulator.agents.build_agent import BUILD_OPTIONS, get_valid_build_mask
from civulator.district_model import DISTRICTS, KIND_WONDER
from civulator.game.availability import player_can_build
from civulator.game.city import City
from civulator.game.districts import can_place_district
from civulator.game.housing import housing
from civulator.game.unit import WorkerUnit
from civulator.game.victory import determine_outcome, score_breakdown
from civulator.game import GameEnvironment, resolve_size_and_players
from civulator.unit_model import CAPITAL_BUILDING

STEP_LIMIT = 200_000
DISTRICT_CHANCE = 0.1  # per city per own turn start


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
        techs = [env.episode_stats[i]["techs_researched"] for i in range(num_players)]
        civics = [env.episode_stats[i]["civics_researched"] for i in range(num_players)]
        governments = [p.government for p in env.players]
        policies = [list(p.policies) for p in env.players]
        print(f"round {round_no:4d}  tiles_owned={owned}  cities={cities}  "
              f"population={pop}  culture_claims={claims}  housing={house}  "
              f"pop_by_player={pops}  growth_slowed_turns={slowed}  "
              f"techs_researched={techs}  civics_researched={civics}  "
              f"governments={governments}  policies={policies}  "
              f"{gold_line()}  {loyalty_line()}  {improvement_line()}  "
              f"t={time.perf_counter() - t0:.1f}s")

    def gold_line():
        """Per player: treasury (whole gold), upkeep paid (whole gold),
        units disbanded, routes opened / running, purchases (tenths spent)."""
        stats = [env.episode_stats[i] for i in range(num_players)]
        return (f"treasury={[p.gold // 10 for p in env.players]}  "
                f"maintenance_paid={[s['gold_maintenance'] // 10 for s in stats]}  "
                f"units_disbanded={[s['units_disbanded'] for s in stats]}  "
                f"routes_established={[s['trade_routes_established'] for s in stats]}  "
                f"routes_running={[len(p.routes) for p in env.players]}  "
                f"purchases_gold_faith_tenths="
                f"{[(s['gold_spent_purchases'], s['faith_spent_purchases']) for s in stats]}")

    def improvement_line():
        """Per player: improvements its Workers built (the episode counter),
        improvements standing on the tiles its cities own, and its Workers
        alive (#116 P8)."""
        built = [env.episode_stats[i]["improvements_built"] for i in range(num_players)]
        standing = [sum(len(env.map.get_tile(pos).improvements)
                        for city in p.cities for pos in env.map.tiles_of_city(city.city_id))
                    for p in env.players]
        workers = [sum(isinstance(u, WorkerUnit) for u in p.units) for p in env.players]
        return (f"improvements_built={built}  improvements_standing={standing}  "
                f"workers_alive={workers}")

    def loyalty_line():
        """Per player: (lowest, mean) loyalty of its cities -- None without a
        city -- and the cities it lost / gained by loyalty flips (#116 P7)."""
        spread = []
        for p in env.players:
            values = [c.loyalty for c in p.cities]
            spread.append((min(values), round(sum(values) / len(values), 1)) if values else None)
        stats = [env.episode_stats[i] for i in range(num_players)]
        return (f"loyalty_min_mean={spread}  "
                f"flips_out_in={[(s['cities_flipped_out'], s['cities_flipped_in']) for s in stats]}")

    district_rng = random.Random(args.seed)
    placed = 0
    water_cities = set()      # city ids that ever held a complete water-adjusting district
    water_gain = []           # housing tenths a city gained from it, at sight

    def district_turn(city):
        nonlocal placed
        names = [n for n in DISTRICTS if player_can_build(city.player, "district", n)]
        if district_rng.random() < DISTRICT_CHANCE and names:
            name = district_rng.choice(names)
            tiles = [pos for pos in sorted(env.map.tiles_of_city(city.city_id))
                     if can_place_district(city, name, pos)]
            if tiles and env.place_district(city, name, district_rng.choice(tiles)):
                placed += 1
        if city.current_production is None:
            for d in city.districts:
                if not d.complete and city.produce_district(d.type):
                    break
        for d in city.districts:
            spec = DISTRICTS[d.type]
            if d.complete and spec.water_housing_min is not None and city.city_id not in water_cities:
                water_cities.add(city.city_id)
                d.complete = False
                without = housing(city)
                d.complete = True
                water_gain.append(housing(city) - without)

    t0 = time.perf_counter()
    log(0)
    next_log = args.every
    last_player = -1
    lowest_seen = [None] * num_players   # per player, over every round end (#116 P7)
    last_round = env.turn_counter
    steps = 0
    while not env.done and steps < STEP_LIMIT:
        steps += 1
        if env.current_player.player_index != last_player:
            for city in env.current_player.cities:
                district_turn(city)
                if city.current_production is None:
                    mask = get_valid_build_mask(city)
                    valid = [BUILD_OPTIONS[i] for i in range(len(BUILD_OPTIONS)) if mask[i] > 0]
                    option = random.choice(valid)
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
        if env.turn_counter != last_round:  # a round just ended: loyalty moved
            last_round = env.turn_counter
            for p in env.players:
                for c in p.cities:
                    low = lowest_seen[p.player_index]
                    lowest_seen[p.player_index] = c.loyalty if low is None else min(low, c.loyalty)
        while next_log <= args.rounds and env.turn_counter > next_log:
            log(next_log)
            next_log += args.every
    log(env.turn_counter)
    all_districts = [d for p in env.players for c in p.cities for d in c.districts]
    print(f"districts placed={placed} completed={sum(d.complete for d in all_districts)} "
          f"by_type={ {n: sum(d.type == n and d.complete for d in all_districts) for n in DISTRICTS} } "
          f"water_housing_cities={len(water_cities)} water_housing_gain_tenths={sorted(water_gain)} "
          f"yields={[{k: v for k, v in env.episode_stats[i].items() if k.startswith('district_yield_') and v} for i in range(num_players)]}")
    print(f"wonders completed={[env.episode_stats[i]['wonders_completed'] for i in range(num_players)]} "
          f"races_lost={[env.episode_stats[i]['wonder_races_lost'] for i in range(num_players)]} "
          f"held={[[d.type for c in p.cities for d in c.districts if d.complete and DISTRICTS[d.type].kind == KIND_WONDER] for p in env.players]} "
          f"placed_unfinished={[[d.type for c in p.cities for d in c.districts if not d.complete and DISTRICTS[d.type].kind == KIND_WONDER] for p in env.players]}")
    for player in env.players:
        print(f"techs {player.name}: researched={env.episode_stats[player.player_index]['techs_researched']} "
              f"current={player.current_tech} science_pool_tenths={player.science} "
              f"order={player.techs}")
        print(f"civics {player.name}: researched={env.episode_stats[player.player_index]['civics_researched']} "
              f"current={player.current_civic} culture_pool_tenths={player.culture} "
              f"government={player.government} policies={player.policies} "
              f"order={player.civics}")
    print(f"gold {gold_line()}")
    print(f"loyalty {loyalty_line()}  lowest_after_any_round={lowest_seen}")
    print(f"improvements {improvement_line()}")
    winner, victory = determine_outcome(env)
    print(f"victory winner={winner} victory={victory} "
          f"palaces_held={[sum(CAPITAL_BUILDING in c.buildings for c in p.cities) for p in env.players]} "
          f"score={[sum(score_breakdown(p).values()) for p in env.players]} "
          f"terms={[score_breakdown(p) for p in env.players]}")
    print(f"done={env.done} steps={steps} wall={time.perf_counter() - t0:.1f}s "
          f"luxuries_accessible={[env.episode_stats[i]['luxuries_accessible'] for i in range(num_players)]} "
          f"amenity_surplus_mean_tenths={[env.episode_stats[i]['amenity_surplus_mean'] for i in range(num_players)]} "
          f"cities_unhappy_rounds={[env.episode_stats[i]['cities_unhappy_rounds'] for i in range(num_players)]} "
          f"units_refused_resource={[env.episode_stats[i]['units_refused_resource'] for i in range(num_players)]} "
          f"encampment_breaches={[env.episode_stats[i]['encampment_breaches'] for i in range(num_players)]} "
          f"encampment_strikes={[env.episode_stats[i]['encampment_strikes'] for i in range(num_players)]} "
          f"regional_production_tenths={[env.episode_stats[i]['regional_production'] for i in range(num_players)]} "
          f"naval_units_built={[env.episode_stats[i]['naval_units_built'] for i in range(num_players)]} "
          f"sea_routes={[env.episode_stats[i]['sea_routes'] for i in range(num_players)]} "
          f"overseas_routes={[env.episode_stats[i]['overseas_routes'] for i in range(num_players)]} "
          f"pantheons_chosen={[env.episode_stats[i]['pantheons_chosen'] for i in range(num_players)]} "
          f"faith_spent_religion_tenths={[env.episode_stats[i]['faith_spent_religion'] for i in range(num_players)]} "
          f"pantheons={[p.pantheon for p in env.players]} "
          f"religions_founded={[env.episode_stats[i]['religions_founded'] for i in range(num_players)]} "
          f"beliefs_added={[env.episode_stats[i]['beliefs_added'] for i in range(num_players)]} "
          f"founder_pay_tenths={[env.episode_stats[i]['founder_pay_tenths'] for i in range(num_players)]} "
          f"religions={[None if p.religion is None else p.religion.beliefs for p in env.players]} "
          f"follower_cities={[sum(c.religion == p.player_index for q in env.players for c in q.cities) if p.religion is not None else 0 for p in env.players]} "
          f"faith_pool_tenths={[p.faith for p in env.players]}")


if __name__ == "__main__":
    main()
