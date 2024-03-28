# -*- coding: utf-8 -*-
"""
Created on Thu Mar 28 11:58:26 2024

@author: steen
"""

class CityNameGenerator:
    def __init__(self):
        print('City Name generator online')
                
        self.roman_cities = ['Rome',
                             'Ostia',
                             'Antium',
                             'Cumae',
                             'Aquileia',
                             'Ravenna', 
                             'Puteoli',
                             'Arretium', 
                             'Mediolanum', 
                             'Lugdunum', 
                             'Arpinum', 
                             'Setia',
                             'Velitrae',
                             'Durocortorum',
                             'Brundisium',
                             'Caesaraugusta',
                             'Palmyra',
                             'Hispalis',
                             'Caesarea',
                             'Artaxata',
                             'Pompeii',
                             ]        
        self.greece_cities = ['Athens',
                              'Delphi',
                              ]
        self.roman_city_counter = 0
        self.greece_city_counter = 0

        
    def get_next_city_name(self, nation='Rome'):
        if nation == 'Rome':
            self.roman_city_counter += 1
            return self.roman_cities[self.roman_city_counter-1]
        if nation == 'Greece':
            self.greece_city_counter += 1
            return self.greece_cities[self.greece_city_counter-1]
            
    

        



"""
more roman cities


Paphos	Site of the Paphos district in Cyprus
Salonae	Capital of the Roman Dalmatia Province, near Split in Croatia
Eburacum	Modern day York, England
Lauriacum	Legionary town on the Danube Limes, near Linz in Austria
Verona	Capital of Verona Province
Colonia Agrippina	Capital of the Roman Germania Inferior Province, modern day Cologne, Germany
Narbo	Modern Narbonne, city in the French Occitanie Region
Tingi	Modern Tangier, Morocco
Sarmizegetusa	Capital of the Dacians, now Romania
Sirmium	Capital of the Roman Pannonia Inferior Province, modern day Sremska Mitrovica, Serbia
"""