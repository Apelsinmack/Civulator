using State;
using State.Enums;
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics.Tracing;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Game
{
    internal class ConsoleGui
    {
        private static string _emptyTile = "{0,-3}";

        private static void SetTerrainConsoleColor(TerrainType terrainType)
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

        private static void PrintFirstMapRow(List<Tile> tiles)
        {
            foreach (Tile tile in tiles)
            {
                PrintTile(tile, true);
                PrintVoid();
            }
            Console.WriteLine();
        }

        private static void PrintLastMapRow(List<Tile> tiles)
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

        private static void PrintMapRow(List<Tile> tiles, bool isFirstPart)
        {
            bool isEven = true;
            foreach (Tile tile in tiles)
            {
                PrintTile(tile, isEven == isFirstPart);
                isEven = !isEven;
            }
            Console.WriteLine();
        }

        public static void PrintTile(Tile tile, bool printContent)
        {
            string content = GetTileContent(tile, printContent);
            SetTerrainConsoleColor(tile.Terrain.Type);
            Console.Write(_emptyTile, content);
        }

        private static string GetTileContent(Tile tile, bool printContent)
        {
            Unit unit = tile.Units.FirstOrDefault();
            if (!printContent || unit == null)
            {
                Console.ForegroundColor = ConsoleColor.White;
                //return tile.Index.ToString();
                return String.Empty;
            }
            Console.ForegroundColor = unit.Owner.Leader.Color;
            switch (unit.Type)
            {
                case UnitType.Scout:
                    return "Sc";
                case UnitType.Warrior:
                    return "Wa";
                default:
                    return string.Empty;
            }
        }

        public static void PrintVoid()
        {
            Console.BackgroundColor = ConsoleColor.Black;
            Console.Write(_emptyTile, String.Empty);
        }

        public static void PrintWorld(World world)
        {
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
        }
    }
}
