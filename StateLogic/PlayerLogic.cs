﻿using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Threading.Tasks;

namespace StateLogic
{
    public static class PlayerLogic
    {
        public static Player GetCurrentPlayer(World world)
        {
            int currentTurn = world.Players.Min(Player => Player.Turn);
            return world.Players.Find(player => player.Turn == currentTurn);
        }

        public static void InitPlayerTurn(World world, Player player) {
            UnitLogic.ResetUnitMovements(world, player);
            UnitLogic.FortifyUnits(world, player);
        }

        public static void KillPlayer(World world, Player player) {
            player.Dead = true;
            foreach(var tile in world.Map.Tiles.Where(tile => tile.Value.Units.Any(unit => unit.Owner.Id == player.Id)))
            {
                tile.Value.Units.RemoveAll(unit => unit.Owner.Id == player.Id);
            }
        }
    }
}
