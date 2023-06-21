﻿namespace State
{
    [Serializable]
    public class World
    {
        public Map Map { get; set; }
        public List<Player> Players { get; set; }
        public Victory Victory { get; set; }

        public World(Map map, List<Player> players)
        {
            Map = map;
            Players = players;
            Victory = new Victory();
        }
    }
}