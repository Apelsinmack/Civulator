using Data;
using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Reflection;
using System.Reflection.Metadata.Ecma335;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public class UnitLogic : IUnitLogic
    {
        private World _world;
        private Unit? _unit;

        public UnitLogic(World world)
        {
            _world = world;
        }

        public void SetCurrentUnit(Unit unit)
        {
            _unit = _world.Units[unit.Index];
        }

        public void Disband()
        {
            _world.Map.Tiles[_unit.TileIndex].UnitIndexes.Remove(_unit.Index);
            _unit.Owner.UnitIndexes.Remove(_unit.Index);
            _world.Units.Remove(_unit.Index);
        }

        public void DisbandAllUnits(Player owner)
        {
            foreach (int index in owner.UnitIndexes.ToList())
            {
                Unit unit = _world.Units[index];
                _world.Map.Tiles[unit.TileIndex].UnitIndexes.Remove(index);
                unit.Owner.UnitIndexes.Remove(index);
                _world.Units.Remove(index);
            }
            owner.UnitIndexes.Clear(); //TODO: Is this needed?
        }

        public void Fortify()
        {
            _unit.MovementLeft = 0;
            _unit.Fortifying = true;
        }

        public void BuildCity(ICityLogic cityLogic)
        {
            if (_unit.Class == UnitType.Settler)
            {
                cityLogic.GenerateCity(_unit.Owner, _world.Map.Tiles[_unit.TileIndex]);
                Disband();
            }
        }

        public void MoveUnit(int newTileIndex)
        {
            Unit unit = _world.Units[_unit.Index];
            _world.Map.Tiles[_unit.TileIndex].UnitIndexes.Remove(unit.Index);
            unit.MovementLeft--;
            unit.TileIndex = newTileIndex;
            _world.Map.Tiles[newTileIndex].UnitIndexes.Add(unit.Index);
            MapLogic.ExploreFromTile(_world, unit.Owner, newTileIndex, UnitClass.ByType[unit.Class].SightRange);
        }

        public Unit GenerateUnit(UnitType unitClass, Player owner, int tileIndex)
        {
            int index = 0;
            if (_world.Units.Count > 0)
            {
                index = _world.Units.Max(unit => unit.Key) + 1;
            }
            Unit unit = new Unit(index, unitClass, owner, tileIndex, UnitClass.ByType[unitClass].Movement);
            _world.Units.Add(index, unit);
            _world.Map.Tiles[tileIndex].UnitIndexes.Add(index);
            owner.UnitIndexes.Add(index);
            MapLogic.ExploreFromTile(_world, owner, tileIndex, UnitClass.ByType[unitClass].SightRange);

            return unit;
        }

        public void ResetUnitMovements(Player owner)
        {
            foreach (int index in owner.UnitIndexes)
            {
                _world.Units[index].MovementLeft = UnitClass.ByType[_world.Units[index].Class].Movement;
            }
        }

        public void FortifyUnits(Player owner)
        {
            foreach (int index in owner.UnitIndexes)
            {
                if (_world.Units[index].Fortifying)
                {
                    _world.Units[index].Fortifying = false;
                    _world.Units[index].Fortified = true;
                }
            }
        }

        public IEnumerable<KeyValuePair<int, Unit>>? GetUnfortifiedUnits(Player player)
        {
            return _world.Units.Where(unit => player.UnitIndexes.Contains(unit.Key) && !unit.Value.Fortifying && !unit.Value.Fortified);
        }

        public IEnumerable<KeyValuePair<int, Unit>>? GetAllUnits(Player player)
        {
            return _world.Units.Where(unit => player.UnitIndexes.Contains(unit.Key));
        }
    }
}
