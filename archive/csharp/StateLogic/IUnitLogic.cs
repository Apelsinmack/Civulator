using State;
using State.Enums;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Logic
{
    public interface IUnitLogic
    {
        void SetCurrentUnit(Unit unit);

        void ResetUnitMovements(Player owner);

        void FortifyUnits(Player owner);

        void Fortify();

        void BuildCity(ICityLogic cityLogic);

        void MoveUnit(int newTileIndex);

        Unit GenerateUnit(UnitType unitClass, Player owner, int tileIndex);

        void Disband();

        void DisbandAllUnits(Player owner);

        IEnumerable<KeyValuePair<int, Unit>>? GetUnfortifiedUnits(Player player);

        IEnumerable<KeyValuePair<int, Unit>>? GetAllUnits(Player player);
    }
}
