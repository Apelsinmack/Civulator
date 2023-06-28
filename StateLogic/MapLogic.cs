using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public class MapLogic
    {
        private int _mapBase;
        private int _mapHeight;
        private TileLogic _tileLogic;
        public int MapBase => _mapBase;
        public int MapHeight => _mapHeight;


        public MapLogic(int mapBase, int mapHeight)
        {
            _mapBase = mapBase;
            _mapHeight = mapHeight;
            _tileLogic = new TileLogic();
        }

        public Map GenerateMap()
        {
            Dictionary<int, Tile> tiles = new Dictionary<int, Tile>();

            for (int i = 0; i < _mapBase * _mapHeight; i++)
            {
                tiles.Add(i, _tileLogic.GenerateTile(i));
            }

            return new Map(_mapBase, _mapHeight, tiles);
        }
    }
}
