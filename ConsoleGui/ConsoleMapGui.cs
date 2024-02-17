using State;
using State.Enums;
using Logic;
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics.Tracing;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Gui
{
    public class ConsoleMapGui
    {
        private World? _world;
        private Player? _currentPlayer;
        private bool _spectator;
        private readonly string _emptyTile = "{0,-3}";

        private void SetTerrainConsoleColor(TerrainType terrainType)
        {
            switch (terrainType)
            {
                case TerrainType.Plains:
                    Console.BackgroundColor = ConsoleColor.Yellow;
                    break;
                case TerrainType.Grassland:
                    Console.BackgroundColor = ConsoleColor.Green;
                    break;
                case TerrainType.Hills:
                    Console.BackgroundColor = ConsoleColor.DarkGreen;
                    break;
                default:
                    Console.BackgroundColor = ConsoleColor.Black;
                    break;
            }
        }

        private void PrintLastMapRowOLD(List<Tile> tiles)
        {
            bool isEven = true;

            foreach (Tile tile in tiles)
            {
                if (isEven)
                {
                    PrintVoid();
                }
                else
                {
                    PrintTile(tile, false);
                }
                isEven = !isEven;
            }
            Console.WriteLine();
        }

        private void PrintTile(Tile tile, bool printUnits)
        {
            if (_spectator || _currentPlayer.ExploredTileIndexes.Contains(tile.Index))
            {
                SetTerrainConsoleColor(tile.Terrain.Type);
                string content = GetTileContent(tile, printUnits);
                Console.Write(_emptyTile, content);
            }
            else
            {
                PrintVoid();
            }
        }

        private string GetTileContent(Tile tile, bool printUnits)
        {
            State.Unit? unit = null;
            if (tile.UnitIndexes.Count > 0)
            {
                unit = _world.Units[tile.UnitIndexes.FirstOrDefault()];
            }
            if (printUnits && unit != null)
            {
                Console.ForegroundColor = unit.Owner.Leader.Color;
                return unit.Class.ToString().Substring(0, 2);
            }

            if (!printUnits && tile.City != null)
            {
                Console.BackgroundColor = tile.City.Owner.Leader.Color;
                Console.ForegroundColor = ConsoleColor.Black;
                return $" {tile.City.Size}";
            }

            Console.ForegroundColor = ConsoleColor.White;
            //return tile.Index.ToString();
            return String.Empty;
        }

        private void PrintVoid()
        {
            Console.BackgroundColor = ConsoleColor.Black;
            Console.Write(_emptyTile, String.Empty);
        }

        public ConsoleMapGui(bool spectator = false)
        {
            _spectator = spectator;
        }

        public void PrintWorld(World world, Player currentPlayer, List<string> log)
        {
            _world = world;
            _currentPlayer = currentPlayer;
            Console.Clear();
            List<Tile> firstPart = new List<Tile>();
            List<Tile> secondPart = new List<Tile>();
            List<Tile> latestPart = new List<Tile>();

            bool isFirstRow = true;
            bool isEven = true;

            foreach (Tile tile in world.Map.Tiles.Values)
            {
                bool isEdge = (tile.Index + 1) % world.Map.MapWidth == 0;
                bool isRowEven = (tile.Index / world.Map.MapWidth) % 2 == 1;
                bool isFirstCellInRow = tile.Index % world.Map.MapWidth == 0;

                if (isRowEven && isFirstCellInRow)
                {
                    PrintVoid();
                }

                PrintTile(tile, false);
                PrintTile(tile, true);


                if (isEdge)
                {
                    if (!isRowEven)
                    {
                        PrintVoid();
                    }
                    Console.WriteLine();
                }
            }
            PrintLastMapRowOLD(latestPart);
            Console.ResetColor();
            Console.ForegroundColor = _currentPlayer.Leader.Color;
            log.ForEach(line => Console.WriteLine(line));
            Console.ResetColor();
        }
    }
}
