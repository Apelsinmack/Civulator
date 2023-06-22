using State;
using State.Enums;
using StateLogic;
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics.Tracing;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Gui
{
    public class ConsoleGui
    {
        private World _world;
        private Player _currentPlayer;
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

        private void PrintFirstMapRow(List<Tile> tiles)
        {
            foreach (Tile tile in tiles)
            {
                PrintTile(tile, true);
                PrintVoid();
            }
            Console.WriteLine();
        }

        private void PrintLastMapRow(List<Tile> tiles)
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

        private void PrintMapRow(List<Tile> tiles, bool isFirstPart)
        {
            bool isEven = true;
            foreach (Tile tile in tiles)
            {
                PrintTile(tile, isEven == isFirstPart);
                isEven = !isEven;
            }
            Console.WriteLine();
        }

        private void PrintTile(Tile tile, bool printUnits)
        {
            if (_currentPlayer.ExploredTileIndexes.Contains(tile.Index))
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
            Unit? unit = null;
            if(tile.UnitIndexes.Count > 0)
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

        public void PrintWorld(World world, List<string> log)
        {
            _world = world;
            _currentPlayer = PlayerLogic.GetCurrentPlayer(world);
            Console.Clear();
            List<Tile> firstPart = new List<Tile>();
            List<Tile> secondPart = new List<Tile>();
            List<Tile> latestPart = new List<Tile>();

            bool isFirstRow = true;
            bool isEven = true;

            foreach (Tile tile in world.Map.Tiles.Values)
            {
                bool isEdge = (tile.Index + 1) % world.Map.MapBase == 0;

                if (isFirstRow)
                {
                    if (isEven)
                    {
                        firstPart.Add(tile);
                    }
                    secondPart.Add(tile);
                }
                else
                {
                    if (isEven)
                    {
                        firstPart.Add(tile);
                        secondPart.Add(tile);
                    }
                    else
                    {
                        firstPart.Add(latestPart[secondPart.Count]);
                        secondPart.Add(tile);
                    }
                }

                isEven = !isEven;

                if (isEdge)
                {
                    if (isFirstRow)
                    {
                        PrintFirstMapRow(firstPart);
                        PrintMapRow(secondPart, false);
                    }
                    else
                    {
                        PrintMapRow(firstPart, true);
                        PrintMapRow(secondPart, false);
                    }
                    isEven = true;
                    isFirstRow = false;
                    latestPart = secondPart.ToList();
                    firstPart = new List<Tile>();
                    secondPart = new List<Tile>();
                }
            }
            PrintLastMapRow(latestPart);
            Console.ResetColor();
            Console.ForegroundColor = _currentPlayer.Leader.Color;
            log.ForEach(line => Console.WriteLine(line));
            Console.ResetColor();
        }
    }
}
