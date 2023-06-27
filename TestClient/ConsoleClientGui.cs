using Api.IncomingCommands.Enums;
using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace TestClient
{
    internal class ConsoleClientGui
    {
        public enum PlayerMenu
        {
            CycleUnits,
            CycleAllUnits,
            CycleCities,
            CycleAllCities,
            EndTurn
        }

        public enum BuildTypeMenu
        {
            Units,
            Buildings
        }

        public void PrintMenu()
        {
            Console.WriteLine("Choose what to to do:");
            Console.WriteLine("1: Cycle units");
            Console.WriteLine("2: Cycle all units");
            Console.WriteLine("3: Cycle cities");
            Console.WriteLine("4: Cycle all cities");
            Console.WriteLine("e: End turn");
        }

        public BuildTypeMenu PrintBuildAddToBuildQueueMenu(City city)
        {
            Console.WriteLine($"What should {city.Name} add to build queue?");
            Console.WriteLine("1: Units");
            Console.WriteLine("2: Buildings");

            while (true)
            {
                switch (Console.ReadLine())
                {
                    case "1":
                        return BuildTypeMenu.Units;
                    case "2":
                        return BuildTypeMenu.Buildings;
                }
            }
        }

        public UnitType PrintBuildUnitMenu(City city)
        {
            Console.WriteLine($"What unit should {city.Name} build?");
            Console.WriteLine($"1: {UnitType.Scout}");
            Console.WriteLine($"2: {UnitType.Settler}");
            Console.WriteLine($"3: {UnitType.Warrior}");

            while (true)
            {
                switch (Console.ReadLine())
                {
                    case "1":
                        return UnitType.Scout;
                    case "2":
                        return UnitType.Settler;
                    case "3":
                        return UnitType.Warrior;
                }
            }
        }

        public BuildingType PrintBuildBuildingMenu(City city)
        {
            Console.WriteLine($"What building should {city.Name} build?");
            Console.WriteLine($"1: {BuildingType.Granary}");

            while (true)
            {
                switch (Console.ReadLine())
                {
                    case "1":
                        return BuildingType.Granary;
                }
            }
        }

        public PlayerMenu ConsoleReadPlayerMenu()
        {
            while (true)
            {
                switch (Console.ReadLine())
                {
                    case "1":
                        return PlayerMenu.CycleUnits;
                    case "2":
                        return PlayerMenu.CycleAllUnits;
                    case "3":
                        return PlayerMenu.CycleCities;
                    case "4":
                        return PlayerMenu.CycleAllCities;
                    case "e":
                        return PlayerMenu.EndTurn;
                }
            }
        }

        public UnitOrderType ConsoleReadUnitOrder()
        {
            while (true)
            {
                switch (Console.ReadLine())
                {
                    case "1":
                        return UnitOrderType.DownLeft;
                    case "2":
                        return UnitOrderType.Down;
                    case "3":
                        return UnitOrderType.DownRight;
                    case "4":
                        return UnitOrderType.UpLeft;
                    case "5":
                        return UnitOrderType.Up;
                    case "6":
                        return UnitOrderType.UpRight;
                    case "f":
                        return UnitOrderType.Fortify;
                }
            }
        }
    }
}
