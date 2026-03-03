using State.Enums;
using State;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Data
{
    public class CityNames
    {
        public static Dictionary<CivilizationType, string[]> ByCivilizationType = new Dictionary<CivilizationType, string[]>();

        internal static void Init()
        {
            Console.WriteLine("Initialize city names...");
            ByCivilizationType = new Dictionary<CivilizationType, string[]>
            {
                { CivilizationType.Babylonians, GetBabylonianCities() },
                { CivilizationType.Norwegian, GetNorwegianCities() },
                { CivilizationType.Chinese, GetChineseCities() },
            };
        }

        internal static string[] GetBabylonianCities()
        {
            string[] cities = { "Borsippa", "Mashkan-shapir", "Eshnunna", "Malgium", "Dur-Kurigalzu", "Mari", "Karkar", "Rapiqum", "Durmuti", "Tuttul", "Kar-Shamash", "Opis", "Shaduppum", "Neribtum", "Haradum", "Ana", "Tutub", "Hit", "Kazallu", "Diniktum", "Der", "Namsum", "Terqa", "Harbu", "Kakkulatum", "Elip", "Yabliya", "Hiritum", "Tell Wilaya" };

            return cities;
        }
        internal static string[] GetNorwegianCities()
        {
            string[] cities = { "Avaldsnes", "Bergen", "Bjarkøy", "Brattahlíð\t", "Drammen", "Frosta", "Hamar", "Hundorp", "Karmøy", "Kristiansand", "Kristiansund", "Kvitsøy", "Moster", "Namsos", "Oslo", "Reykjavík", "Ringerike", "Sandnæs", "Sarpsborg", "Skedsmo", "Skien", "Sogndal", "Stange", "Stavanger", "Stiklestad", "Tjøtta", "Tromsø", "Tønsberg", "Verdal", "Vinland", "Ålesund" };

            return cities;
        }

        internal static string[] GetChineseCities()
        {
            string[] cities = { "Taiyuan", "Chengdu", "Jiaodong", "Changsha", "Longxi", "Guangzhou", "Handan", "Shenyang", "Shanghai", "Wuhan", "Yiyang", "Xiurong", "Chen", "Xingzhou", "Quxian", "Nanjing", "Langfang", "Linzi", "Jiujiang", "Kaifeng", "Xuzhou", "Hefei", "Xinzheng", "Lu’an", "Qufu", "Jiangzhou", "Luoyang", "Yinchuan" };

            return cities;
        }
    }
}
