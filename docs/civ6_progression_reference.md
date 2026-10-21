# Civ 6 (Gathering Storm) reference digest, Ancient to early Renaissance

Compiled for Civulator game-design. Source: Civilization Wiki (civilization.fandom.com), read via the wiki's MediaWiki API (`api.php?action=parse`) because the WebFetch tool returned HTTP 402 for every wiki page. The API returns the same page content (wikitext/rendered HTML), so values are exactly what the pages state. Where a page gives separate Vanilla / Rise and Fall (R&F) / Gathering Storm (GS) values, GS is used and the other is flagged. "n/a (not found)" = not on the pages read. "[conflict]" = two wiki pages disagree; both values given.

Conventions: Sci = science, Cul = culture, Prod = production. Unique (civ-specific) units/buildings/improvements are omitted except where they are wonders. Prerequisites in section 1 and 2 come from the per-tech / per-civic infobox field `reqs` (explicit), cross-checked by inverting the list pages' "Leads to" column (they agree except where flagged).

---

## 1. TECHNOLOGY TREE (Ancient, Classical, Medieval, first Renaissance)

Costs are base costs on Standard speed. Wiki Technology page: techs from an era earlier than the game's World Era cost 20% less, later-era techs 20% more (R&F/GS World Era mechanic). Renaissance techs in the list read "540 / GS 600": 540 is vanilla/R&F, 600 is GS (same pattern 660 vs 730). Medieval costs have no GS split on the list page.

Starting techs (no prerequisite): Pottery, Animal Husbandry, Mining, Sailing, Astrology.

### Ancient era
| Tech | Sci | Prereq | Unlocks (generic) | Eureka |
|---|---|---|---|---|
| Pottery | 25 | - | Granary; Great Bath (wonder, GS); allows harvesting Maize, Rice, Wheat | none |
| Animal Husbandry | 25 | - | Pasture, Camp; reveals Horses; allows harvesting Cattle, Sheep, Deer | none |
| Mining | 25 | - | Mine, Quarry; allows chopping Woods, harvesting Copper | none |
| Sailing | 50 | - | Fishing Boats, Galley; Builders can embark | Found a city on the Coast |
| Astrology | 50 | - | Holy Site district, Shrine, Stonehenge (wonder) | Find a Natural Wonder |
| Irrigation | 50 | Pottery | Plantation, Hanging Gardens (wonder); allows clearing Marsh, harvesting Bananas | Build a Farm on a Bonus resource |
| Writing | 50 | Pottery | Campus district, Library | Meet another civilization |
| Archery | 50 | Animal Husbandry | Archer, Temple of Artemis (wonder) | Kill a unit with a Slinger |
| Masonry | 80 | Mining | Ancient Walls, Pyramids (wonder), Battering Ram; allows harvesting Stone (the list page also shows the Great Wall, which is China's unique improvement, omitted) | Build a Quarry |
| Bronze Working | 80 | Mining | Encampment district, Barracks, Spearman; reveals Iron; allows chopping Rainforest | Kill 3 Barbarians |
| Wheel | 80 | Mining | Water Mill, Heavy Chariot | Build a Mine on any resource |

### Classical era
| Tech | Sci | Prereq | Unlocks (generic) | Eureka |
|---|---|---|---|---|
| Celestial Navigation | 120 | Sailing, Astrology | Harbor district, Lighthouse, Great Lighthouse (wonder); Traders can embark; allows harvesting Fish, Crabs | Improve 2 Sea resources |
| Currency | 120 | Writing | Commercial Hub district, Market | Make a Trade Route |
| Horseback Riding | 120 | Archery | Stable, Horseman | Build a Pasture |
| Iron Working | 120 | Bronze Working | Swordsman | Build an Iron Mine |
| Shipbuilding | 200 | Sailing | Quadrireme, Colossus (wonder); all land units can embark | Own 2 Galleys |
| Mathematics | 200 | Currency | Petra (wonder), Diplomatic Quarter, Consulate; +1 Movement for all naval units | Build 3 different specialty districts |
| Construction | 200 | Masonry, Horseback Riding | Terracotta Army (wonder), Lumber Mill (GS only; in Vanilla/R&F it is at Machinery), Siege Tower (list page and Vanilla/R&F; GS: the Siege Tower unit page says "Unlocked with Machinery") | Build a Water Mill |
| Engineering | 200 | Wheel | Aqueduct, Catapult, Machu Picchu (wonder) | Build Ancient Walls |

### Medieval era
| Tech | Sci | Prereq | Unlocks (generic) | Eureka |
|---|---|---|---|---|
| Military Tactics | 300 | Mathematics | Pikeman, Huey Teocalli (wonder) | Kill a unit with a Spearman |
| Buttress (GS only) | 300 | Shipbuilding, Mathematics | Dam, Hagia Sophia (wonder, GS) | Build a Classical-era-or-later Wonder |
| Apprenticeship | 300 | Currency, Horseback Riding | Industrial Zone district, Workshop, Man-At-Arms; +1 Prod on Mines | Build 3 Mines |
| Machinery | 300 | Iron Working, Engineering | Crossbowman, Skirmisher (GS), Kilwa Kisiwani (wonder); Lumber Mill (Vanilla/R&F only); Siege Tower in GS (see Construction) | Own 3 Archers |
| Stirrups | 390 | Horseback Riding, Apprenticeship | Knight; +1 Food on Pastures | Have the Feudalism civic |
| Education | 390 [conflict: per-tech page says 335] | Mathematics, Apprenticeship | University; Hagia Sophia (Vanilla/R&F only) | Earn a Great Scientist |
| Military Engineering | 390 [conflict: per-tech page says 335] | Construction | Armory, Military Engineer, Trebuchet; reveals Niter | Build an Aqueduct |
| Castles | 390 | Construction | Medieval Walls, Alhambra (wonder), Courser | GS: adopt a government with 6 inherent policy slots (Vanilla/R&F: have a government with 6 slots) |

### Renaissance era (only techs needed for the requested units/buildings/wonders)
| Tech | Sci GS (Vanilla/R&F) | Prereq | Unlocks (generic) | Eureka |
|---|---|---|---|---|
| Cartography | 600 (540) | Buttress (GS list). [conflict: per-tech page says Shipbuilding] | Caravel, Casa de Contratacion (wonder); +1 Gold on Fishing Boats (R&F +2; per-tech page says +2); naval and embarked units can enter Ocean | Build 2 Harbors |
| Mass Production | 600 (540) | Military Tactics, Buttress, Education (GS list inversion). [conflict: per-tech page says Education, Shipbuilding] | Shipyard, Venetian Arsenal (wonder); +1 Housing to Kampungs | Build a Lumber Mill |
| Banking | 600 (540) | Stirrups, Education | Bank, Great Zimbabwe (wonder); +2 Gold on Quarries (Vanilla/R&F only) | Have the Guilds civic |
| Gunpowder | 600 (540) | Apprenticeship, Stirrups, Military Engineering | Musketman; GS: +1 Prod on Quarries. Makes Warrior obsolete (Warrior infobox) | Build an Armory |
| Printing | 600 (540) | Machinery | Forbidden City (wonder); +1 diplomatic visibility level on all civs; doubles Tourism from Great Works of Writing | Build 2 Universities |
| Metal Casting | 730 (660) | Gunpowder | Bombard, Pike and Shot | Own 2 Crossbowmen |
| Siege Tactics | 730 (660) | Castles | Renaissance Walls, Fort | Own 2 Trebuchets |

Notes: Great Bath is listed under Pottery on the list page; Colossus under Shipbuilding. Casa de Contratacion needs Cartography (not Mercantilism). Wonder tech/civic requirements are re-checked in section 5.

Sources: https://civilization.fandom.com/wiki/List_of_technologies_in_Civ6 ; https://civilization.fandom.com/wiki/Technology_(Civ6) ; per-tech pages https://civilization.fandom.com/wiki/<Tech>_(Civ6) (Pottery ... Metal_Casting).

---

## 2. CIVICS TREE (Ancient, Classical, Medieval, Renaissance up to Diplomatic Service)

Culture costs on Standard speed. Medieval and Renaissance civics have two costs on the list page: Vanilla/R&F and Gathering Storm (GS). Ancient and Classical costs have no split. "+1 Gov" = grants a Governor title (R&F/GS only). "+1 Env" = grants 1 Envoy. Unique (civ-specific) units/buildings are omitted. Inspiration = the civic equivalent of a tech Eureka (size of the boost: section 14). Card types: Mil = Military, Eco = Economic, Dip = Diplomatic, Wild = Wildcard.

### Ancient
| Civic | Cul | Prereq | Unlocks (policy cards; other) | Inspiration |
|---|---|---|---|---|
| Code of Laws | 20 | - | Cards: Survey (Mil), Discipline (Mil), God King (Eco), Urban Planning (Eco). Government: Chiefdom (the government system becomes active) | none |
| Craftsmanship | 40 | Code of Laws | Cards: Ilkum (Eco), Agoge (Mil) | Improve 3 tiles |
| Foreign Trade | 40 | Code of Laws | Cards: Caravansaries (Eco), Maritime Industries (Mil). Unit: Trader. +1 Trade Route capacity. Diplomacy: Joint War (R&F: Join Ongoing War) | Discover a second Continent |
| Military Tradition | 50 | Craftsmanship | Cards: Maneuver (Mil), Strategos (Wild). Grants Flanking and Support combat bonuses to all combat units | Clear a Barbarian Encampment |
| State Workforce | 70 | Craftsmanship | Cards: Conscription (Mil), Corvee (Eco). Government Plaza district (buildings Ancestral Hall, Audience Chamber, Warlord's Throne). +1 Gov | Build any district |
| Early Empire | 70 | Foreign Trade | Cards: Colonization (Eco), Land Surveyors (Eco), Limitanei (Mil, R&F+). Border closing / Open Borders; Casus Belli War of Retribution (R&F+). +1 Gov | Grow civilization to at least 6 population |
| Mysticism | 50 | Foreign Trade | Cards: Inspiration (Wild), Revelation (Wild). Oracle (wonder). +1 Env | Found a Pantheon |

### Classical
| Civic | Cul | Prereq | Unlocks | Inspiration |
|---|---|---|---|---|
| Games and Recreation | 110 | State Workforce | Card: Insulae (Eco). Entertainment Complex district, Arena building, Colosseum (wonder) | Research the Construction technology |
| Political Philosophy | 110 | State Workforce, Early Empire | Cards: Charismatic Leader (Dip), Diplomatic League (Dip). Governments: Autocracy, Classical Republic, Oligarchy. Apadana (wonder) | Meet 3 city-states |
| Drama and Poetry | 110 | Early Empire | Card: Literary Tradition (Wild). Theater Square district, Amphitheater building | Build a Wonder |
| Military Training | 120 | Games and Recreation, Military Tradition | Cards: Raid (Mil), Veterancy (Mil), Equestrian Orders (Mil, GS). Statue of Zeus (wonder). +1 Env | Build an Encampment |
| Defensive Tactics | 175 | Games and Recreation, Political Philosophy | Cards: Bastions (Mil), Limes (Mil). Mausoleum at Halicarnassus (wonder). +1 Gov | Be the target of a Declaration of War |
| Recorded History | 175 | Drama and Poetry, Political Philosophy | Cards: Natural Philosophy (Eco), Praetorium (Dip, R&F+). Great Library (wonder). +1 Gov | Build 2 Campus districts |
| Theology | 120 | Drama and Poetry, Mysticism | Card: Scripture (Eco). Temple building, Mahabodhi Temple (wonder). +1 Env | Found a Religion |

### Medieval (Cul = Vanilla/R&F / GS)
| Civic | Cul V/R&F | Cul GS | Prereq | Unlocks | Inspiration |
|---|---|---|---|---|---|
| Naval Tradition | 200 | 220 | Defensive Tactics | Cards: Naval Infrastructure (Eco), Navigation (Wild). +1 Env | Kill a unit with a Quadrireme |
| Feudalism | 275 | 300 | Defensive Tactics | Cards: Feudal Contract (Mil), Serfdom (Eco). Farms gain +1 Food per 2 adjacent Farms; +1 Faith to Stepwells; GS: +1 Food on Plantations | Build 6 Farms |
| Civil Service | 275 | 300 | Defensive Tactics, Recorded History | Cards: Retainers (Mil), Civil Prestige (Eco, R&F+), Meritocracy (Eco, Vanilla only). Allows Alliances. Meenakshi Temple (wonder, GS). R&F: +1 Prod and +1 Housing to Mekewaps | Grow a city to 10 population |
| Mercenaries | 290 | 340 | Feudalism, Military Training | Cards: Professional Army (Mil), Retinues (Mil, GS), Trade Confederation (Eco), Sack (Mil, Vanilla only). +1 Env | Have 8 land combat units in your military |
| Medieval Faires | 385 | 420 | Feudalism | Cards: Aesthetics (Eco), Medina Quarter (Eco), Merchant Confederation (Dip). Angkor Wat (wonder). +1 Gov | Maintain 4 Trade Routes |
| Guilds | 385 | 420 | Feudalism, Civil Service | Cards: Craftsmen, Town Charters (Eco), Traveling Merchants (Wild). Chichen Itza (wonder). +1 Gov | Build 2 Markets |
| Divine Right | 290 | 340 | Civil Service, Theology | Cards: Chivalry (Mil), Gothic Architecture (Eco). Government: Monarchy. Mont St. Michel, Kotoku-in (wonders) | Build 2 Temples |

### Renaissance (only the five requested)
| Civic | Cul V/R&F | Cul GS | Prereq | Unlocks | Inspiration |
|---|---|---|---|---|---|
| Exploration | 400 | 440 | Mercenaries, Medieval Faires | Cards: Press Gangs (Mil), Colonial Offices (Eco; the GS note on the list page says Diplomatic). Government: Merchant Republic | Build 2 Caravels |
| Reformed Church | 400 | 440 | Divine Right | Cards: Wars of Religion (Mil), Religious Orders (Eco), Simultaneum (Eco). Government: Theocracy. St. Basil's Cathedral (wonder, R&F+) | Have 6 cities following your Religion |
| Humanism | 540 | 600 | Medieval Faires, Guilds | Cards: Frescoes (Wild), Invention (Wild). Taj Mahal (wonder), Art Museum, Archaeological Museum. Vanilla/R&F: +1 Culture to Colossal Heads | Earn a Great Artist |
| Mercantilism | 655 | 720 | Humanism | Cards: Logistics (Mil), Triangular Trade (Eco), Drill Manuals (Mil, GS). Torre de Belem (wonder). Camps +1 Food and +1 Prod | Earn a Great Merchant |
| Diplomatic Service | 540 | 600 | Guilds | Cards: Machiavellianism (Dip), Wisselbanken (Dip, R&F+). Resident Embassies; +1 Spy capacity; allows Spy construction; Casus Belli Holy War, Liberation, Reconquest, Protectorate; +1 Culture to Pairidaezas | Have an alliance with another civilization |

[conflict] The civics list page also names Native Conquest as an Exploration card; the policy list and the Native Conquest page say it is unlocked by Colonialism (Industrial), so it is not counted here. Governor-title civics per the list page: State Workforce, Early Empire, Defensive Tactics, Recorded History, Medieval Faires, Guilds (Civil Service and Humanism do not give one).

Sources: https://civilization.fandom.com/wiki/List_of_civics_in_Civ6 ; https://civilization.fandom.com/wiki/Civic_(Civ6) ; per-civic pages https://civilization.fandom.com/wiki/<Civic>_(Civ6) (Code_of_Laws ... Diplomatic_Service) for the explicit prerequisites and Inspiration text.

---

## 3. GOVERNMENTS (Chiefdom, Tier 1, Tier 2)

Slot totals: Chiefdom 2, Tier 1 = 4, Tier 2 = 6 (Tier 3 = 8, Tier 4 = 10). All slots must be filled to end the turn. A Wildcard slot accepts a card of any type. Switching back to a government you have used before costs Anarchy turns: 2 + 1 per previous adoption (Government page). Government and policies can be changed free when a civic completes, when the slot count changes (new wonder, obsolete card), or by paying a gold tax; R&F adds: when the world era changes, and when a Government Plaza building is built.

| Government | Tier | Unlock civic | Slots M / E / D / W | Influence per turn; envoy threshold; GS Diplomatic Favor | Inherent bonus | Legacy bonus |
|---|---|---|---|---|---|---|
| Chiefdom | 0 | Code of Laws | 1 / 1 / 0 / 0 | 1; n/a; 0 | None | None |
| Autocracy | 1 | Political Philosophy | 1 / 1 / 1 / 1 | 3; 100; 1 | Vanilla: Capital +1 to all yields; +10% Prod toward Wonders. R&F/GS: +1 to all yields for each Government Plaza building, Diplomatic Quarter building and Palace in a city; +10% Prod toward Wonders | Vanilla: +1% wonder Prod per 20 turns of use. R&F/GS: Autocratic Legacy wildcard card (+1 to all yields for each Government Plaza building, Diplomatic Quarter building and Palace in a city) |
| Classical Republic | 1 | Political Philosophy | 0 / 2 / 1 / 1 | 3; 100; 1 | Vanilla: all cities with a district +1 Amenity; +15% Great People points. R&F/GS: all cities with a district +1 Housing and +1 Amenity; +15% Great Person points | Vanilla: +1% Great People points per 15 turns. R&F/GS: Republican Legacy card (all cities with a district +1 Housing and +1 Amenity) |
| Oligarchy | 1 | Political Philosophy | 2 / 1 / 0 / 1 | 3; 100; 1 | Vanilla: all land melee units +4 Combat Strength; +20% unit experience. R&F/GS: land melee, anti-cavalry and naval melee classes +4 CS; +20% unit experience | Vanilla: +1% unit experience per 5 turns. R&F/GS: Oligarchic Legacy card (land melee, anti-cavalry, naval melee +4 CS) |
| Monarchy | 2 | Divine Right | 2 / 1 / 1 / 2 | 5; 150; 2 | Vanilla: +2 Housing in cities with Medieval Walls, +20% influence points (infobox: +50% Prod toward defensive buildings, +1 Housing per wall level). R&F: +1 Housing per level of Walls; +50% Influence Points. GS: same plus +2 Diplomatic Favor for every Renaissance Walls | Vanilla: +1% influence per 10 turns. R&F/GS: Monarchic Legacy card (+1 Housing per level of Walls) |
| Merchant Republic | 2 | Exploration | 1 / 2 / 2 / 1 | 5; 150; 2 | Vanilla: +2 Trade Routes; 15% discount on gold purchases. R&F/GS: +10% Gold in all cities with an established Governor; +15% Prod toward Districts (the Trade Route and discount bonuses are Vanilla only) | Vanilla: +1% gold purchase discount per 15 turns. R&F/GS: Mercantile Legacy card (+10% Gold in all cities with an established Governor) |
| Theocracy | 2 | Reformed Church | 2 / 2 / 1 / 1 | 5; 150; 2 | Vanilla: can buy land combat units with Faith; +5 Religious Strength in theological combat; 15% discount on Faith purchases. R&F/GS text on the page: +5 Religious Strength in Theological Combat; +0.5 Faith per citizen in cities with Governors; 15% discount on purchases with Faith | Vanilla: +1% Faith purchase discount per 15 turns. R&F/GS: Theocratic Legacy card (+5 Religious Strength; +0.5 Faith per citizen in cities with Governors) |

[conflict] The Merchant Republic infobox says era Medieval; the Government list page and its unlock civic (Exploration) say Renaissance. The R&F/GS text on the Government pages drops Theocracy's "can buy land combat units with Faith"; the Faith page says that in R&F this ability comes from building the Grand Master's Chapel, while the City page still credits Theocracy (see sections 8 and 13).

Legacy cards (R&F/GS) are Wildcard policy cards, available after adopting that government AND building a Government Plaza building of that tier (Tier 1: Ancestral Hall / Audience Chamber / Warlord's Throne; Tier 2: Foreign Ministry / Grand Master's Chapel / Intelligence Agency, or Queen's Bibliotheque for Kristina). They can be slotted at any time once that government is no longer active.

Extra policy slots outside governments (Policy card page): Alhambra +1 Military, Big Ben +1 Economic, Potala Palace +1 Diplomatic, Forbidden City +1 Wildcard (lost if the wonder is lost). Max total slots 15 in GS.

Sources: https://civilization.fandom.com/wiki/Government_(Civ6) ; per-government pages https://civilization.fandom.com/wiki/<Government>_(Civ6) (Chiefdom, Autocracy, Classical_Republic, Oligarchy, Monarchy, Theocracy, Merchant_Republic) ; https://civilization.fandom.com/wiki/Policy_card_(Civ6) ; https://civilization.fandom.com/wiki/List_of_policy_cards_in_Civ6

---

## 4. POLICY CARDS (from the civics in section 2)

Card types: Mil, Eco, Dip, Wild. A card becomes obsolete the moment the listed later civic is researched (per-card page field "obsolete_with"); the card in brackets is the replacement card that civic unlocks, where the policy list shows one. GS rule (Policy card page): era-specific cards now work for ALL earlier eras too, not just the two latest. R&F/GS tags show the changed text; unlabeled text is the same in all versions.

### Ancient civics
| Card | Type | Civic | Effect | Obsolete with |
|---|---|---|---|---|
| Survey | Mil | Code of Laws | Doubles experience for recon units | Colonialism (Native Conquest) |
| God King | Eco | Code of Laws | +1 Faith and +1 Gold in the Capital | Theology (Scripture) |
| Discipline | Mil | Code of Laws | +5 Combat Strength when fighting Barbarians | Colonialism (Native Conquest) |
| Urban Planning | Eco | Code of Laws | +1 Prod in all cities | The Enlightenment per card page [conflict: policy list says Colonial Offices supersedes it] |
| Ilkum | Eco | Craftsmanship | +30% Prod toward Builders | Feudalism (Serfdom) |
| Agoge | Mil | Craftsmanship | +50% Prod toward Ancient and Classical era melee, ranged and anti-cavalry units | Feudalism (Feudal Contract) |
| Caravansaries | Eco | Foreign Trade | +2 Gold from all Trade Routes | Mercantilism (Triangular Trade) |
| Maritime Industries | Mil | Foreign Trade | +100% Prod toward Ancient and Classical era naval units | Exploration (Press Gangs) |
| Maneuver | Mil | Military Tradition | +50% Prod toward Ancient and Classical era heavy and light cavalry units | Divine Right (Chivalry) |
| Strategos | Wild | Military Tradition | +2 Great General points per turn | Scorched Earth (Military Organization) |
| Conscription | Mil | State Workforce | Unit maintenance reduced by 1 Gold per turn, per unit | Mobilization (Levee en Masse) |
| Corvee | Eco | State Workforce | +15% Prod toward Ancient and Classical wonders | Divine Right (Gothic Architecture) |
| Land Surveyors | Eco | Early Empire | Reduces the cost of purchasing a tile by 20% | Scorched Earth (Expropriation) |
| Colonization | Eco | Early Empire | +50% Prod toward Settlers | Scorched Earth (Expropriation) |
| Limitanei (R&F+) | Mil | Early Empire | +2 Loyalty per turn for cities with a garrisoned unit | none |
| Inspiration | Wild | Mysticism | +2 Great Scientist points per turn | Nuclear Program |
| Revelation | Wild | Mysticism | +2 Great Prophet points per turn | Humanism (Frescoes / Invention) |

### Classical civics
| Card | Type | Civic | Effect | Obsolete with |
|---|---|---|---|---|
| Insulae | Eco | Games and Recreation | +1 Housing in all cities with at least 2 specialty districts | Medieval Faires (Medina Quarter) |
| Charismatic Leader | Dip | Political Philosophy | +2 Influence Points per turn toward earning city-state Envoys | Totalitarianism |
| Diplomatic League | Dip | Political Philosophy | The first Envoy you send to each city-state counts as 2 Envoys | none |
| Literary Tradition | Wild | Drama and Poetry | +2 Great Writer points per turn | none |
| Raid | Mil | Military Training | Vanilla (list page): yields from pillaging doubled for pillaging improvements. R&F/GS (card page): yields from pillaging and coastal raids +50% | Scorched Earth (Total War) |
| Veterancy | Mil | Military Training | +30% Prod toward Encampment districts and their buildings. GS: also Harbor districts and their buildings | none |
| Equestrian Orders (GS) | Mil | Military Training | All improved Horses and Iron resources yield 1 additional resource per turn | none |
| Bastions | Mil | Defensive Tactics | +6 City Defense Strength, +5 City Ranged Strength | Civil Engineering (Public Works) |
| Limes | Mil | Defensive Tactics | +100% Prod toward defensive buildings | Totalitarianism (Lightning Warfare) |
| Natural Philosophy | Eco | Recorded History | +100% Campus district adjacency bonuses | Class Struggle (Five-Year Plan) |
| Praetorium (R&F+) | Dip | Recorded History | Governors provide +2 Loyalty per turn to their city | Social Media (Communications Office) |
| Scripture | Eco | Theology | +100% Holy Site district adjacency bonuses (replaces God King) | none |

### Medieval civics
| Card | Type | Civic | Effect | Obsolete with |
|---|---|---|---|---|
| Naval Infrastructure | Eco | Naval Tradition | +100% Harbor district adjacency bonuses | Suffrage (Economic Union) |
| Navigation | Wild | Naval Tradition | +2 Great Admiral points per turn | none |
| Feudal Contract | Mil | Feudalism | +50% Prod toward Ancient, Classical, Medieval and Renaissance era melee, ranged and anti-cavalry units | Nationalism (Grande Armee) |
| Serfdom | Eco | Feudalism | Newly trained Builders gain 2 extra build actions | Civil Engineering (Public Works) |
| Retainers | Mil | Civil Service | +1 Amenity for cities with a garrisoned unit | Mass Media (Propaganda) |
| Civil Prestige (R&F+) | Eco | Civil Service | Established Governors with at least 2 Promotions provide +1 Amenity and +2 Housing | none |
| Professional Army | Mil | Mercenaries | Vanilla/R&F: 50% discount on all unit upgrades. GS: 50% Gold discount on all unit upgrades | Urbanization (Force Modernization) |
| Retinues (GS) | Mil | Mercenaries | 50% resource discount on all unit upgrades | Urbanization (Force Modernization) |
| Trade Confederation | Eco | Mercenaries | +1 Culture and +1 Science from international Trade Routes | Capitalism (Market Economy) |
| Merchant Confederation | Dip | Medieval Faires | +1 Gold from each of your Envoys at city-states | none |
| Aesthetics | Eco | Medieval Faires | +100% Theater Square district adjacency bonuses | Professional Sports (Sports Media) |
| Medina Quarter | Eco | Medieval Faires | +2 Housing in all cities with at least 3 specialty districts (replaces Insulae) | Suffrage (New Deal) |
| Craftsmen | Eco (list page: GS type shown as Military) | Guilds | +100% Industrial Zone district adjacency bonuses | Class Struggle (Five-Year Plan) |
| Town Charters | Eco | Guilds | +100% Commercial Hub district adjacency bonuses | Suffrage (Economic Union) |
| Traveling Merchants | Wild | Guilds | +2 Great Merchant points per turn | Capitalism (Laissez-Faire) |
| Chivalry | Mil | Divine Right | +50% Prod toward Industrial era and earlier heavy and light cavalry units (replaces Maneuver) | Totalitarianism (Lightning Warfare) |
| Gothic Architecture | Eco | Divine Right | +15% Prod toward Ancient, Classical, Medieval and Renaissance wonders (replaces Corvee) | Civil Engineering (Skyscrapers) |

Vanilla-only (removed in R&F, therefore not in GS): Meritocracy (Eco, Civil Service: each city +1 Culture for each specialty district it constructs) and Sack (Mil, Mercenaries: pillaging yields doubled for districts).

### Renaissance civics (Exploration, Reformed Church, Humanism, Mercantilism, Diplomatic Service)
| Card | Type | Civic | Effect | Obsolete with |
|---|---|---|---|---|
| Press Gangs | Mil | Exploration | +100% Prod toward Industrial era and earlier naval units (replaces Maritime Industries) | Cold War (International Waters) |
| Colonial Offices | Eco (list page: GS type shown as Diplomatic) | Exploration | +15% faster growth for cities not on your original Capital's continent. R&F: also +3 Loyalty per turn there (replaces Urban Planning per the policy list) | none |
| Wars of Religion | Mil | Reformed Church | +4 Combat Strength when fighting units of civilizations that follow other Religions | none |
| Simultaneum | Eco | Reformed Church | GS: extra Faith from buildings in Holy Sites: +50% if city population is 15 or higher, +50% if district has at least +4 adjacency. (R&F: pop 10 / +3; Vanilla: +100% Faith from Holy Site buildings) | none |
| Religious Orders | Eco | Reformed Church | All religious units +5 Religious Strength in theological combat | none |
| Frescoes | Wild | Humanism | Vanilla/R&F: +2 Great Artist points per turn. GS: +2, plus +2 additional for every Art Museum | none |
| Invention | Wild | Humanism | Vanilla/R&F: +2 Great Engineer points per turn. GS: +4, plus +2 additional for every Workshop | none |
| Logistics | Mil | Mercantilism | +1 Movement if starting turn in friendly territory | none |
| Triangular Trade | Eco | Mercantilism | +4 Gold and +1 Faith from all Trade Routes (replaces Caravansaries) | Globalization (Ecommerce) |
| Drill Manuals (GS) | Mil | Mercantilism | All improved Niter and Coal resources yield 1 additional resource per turn | none |
| Machiavellianism | Dip | Diplomatic Service | +50% Prod toward Spies; spy operations take 25% less time | none |
| Wisselbanken (R&F+) | Dip | Diplomatic Service | Trade Routes to an Ally's city (GS: or a city-state you are Suzerain of) give +2 Food and +2 Prod to both cities; Alliance Points with each ally grow 25% faster | Suffrage (Arsenal of Democracy) |

Legacy (government) cards, R&F/GS, all Wildcard: Autocratic, Republican, Oligarchic, Monarchic, Mercantile, Theocratic Legacy (effects in section 3).

Sources: https://civilization.fandom.com/wiki/List_of_policy_cards_in_Civ6 ; https://civilization.fandom.com/wiki/Policy_card_(Civ6) ; per-card pages https://civilization.fandom.com/wiki/<Card>_(Civ6) (e.g. God_King_(Civ6), Caravansaries_(Civ6), Professional_Army_(Civ6), Native_Conquest_(Civ6)).

---

## 5. WONDERS (Ancient, Classical, Medieval, plus five Renaissance)

General rules (Wonder page + list page header):
- Each wonder exists once in the world. Losing the race: the consolation is 50% of the Production invested (not gold, as in Civ 5).
- A wonder sits on its own tile near a city (not in the city center). Valid tiles hold no district, luxury or strategic resource. A city must already own every required improvement/district/building (or its unique replacement) BEFORE it can start the wonder. Terrain/resources that must be adjacent count even in neutral or foreign territory.
- Once a city has broken ground, no other city of that player can build the same wonder. Completing a wonder immediately expands the city's borders by 2 tiles (where tiles are available). Razing the city loses the wonder permanently.
- The wonder tile cannot be worked but keeps giving adjacency bonuses. Base Tourism per wonder 2, +1 for every new era entered through tech or civic research.
- Industrial-city-state Production bonuses help wonders (Capital +2 Prod per such city-state with 1 Envoy).
- "Flat" in placement is not stated in-game (list-page footnote). Effects apply only to the civ that builds it unless stated.
- Pack tags: P&M = Persia and Macedon pack, B&G = Byzantium and Gaul pack, K&I = Khmer and Indonesia pack, wonder requires that DLC. R&F / GS = needs that expansion.

### Ancient
| Wonder | Prod | Requires | Placement | Effect |
|---|---|---|---|---|
| Etemenanki (Portugal Pack per page) | 220 | Writing | On Floodplains or Marsh | +2 Science and +1 Prod to all Marsh tiles in your empire; +1 Science and +1 Prod on all Floodplains tiles in this city; +2 Science |
| Great Bath (GS) | 180 | Pottery | On a Floodplains tile | +3 Housing; +1 Amenity from entertainment; Floodplains along the river containing the wonder become immune to Flood damage, at the cost of -50% Food and Prod bonuses from flooding; Floodplains tiles of this city gain +1 Faith for each time Flood damage is mitigated |
| Hanging Gardens | 180 | Irrigation | Next to a River | +15% growth in all cities; +2 Housing |
| Oracle | 290 | Mysticism | On Hills | +1 Culture, +1 Faith; Patronage of Great People costs 25% less Faith; Districts in this city provide +2 Great Person points of their type |
| Pyramids | 220 | Masonry | On Desert (incl. Floodplains) without Hills | +2 Culture; grants a free Builder; all Builders get 1 extra build charge |
| Stonehenge | 180 | Astrology | Flat land adjacent to Stone | +2 Faith; grants a free Great Prophet; Great Prophets may found a religion on Stonehenge instead of a Holy Site |
| Temple of Artemis (R&F+) | 180 | Archery | Next to a Camp | +4 Food; +3 Housing; each Camp, Pasture and Plantation within 4 tiles gives +1 Amenity |

### Classical
| Wonder | Prod | Requires | Placement | Effect |
|---|---|---|---|---|
| Apadana (P&M) | 400 | Political Philosophy (civic) | Adjacent to the Capital | +2 Great Work slots; +2 Envoys when you build a wonder (including Apadana) in this city |
| Colosseum | 400 | Games and Recreation (civic) | Flat land adjacent to an Entertainment Complex (R&F+: one with an Arena) | Vanilla: +2 Culture, +3 Amenities to this city and all cities within 6 tiles. R&F/GS: +2 Culture, +2 Amenities and +2 Loyalty to each City Center within 6 tiles |
| Colossus | 400 | Shipbuilding | On Coast, adjacent to land and a Harbor; not on a Lake | +3 Gold; +1 Great Admiral point per turn; +1 Trade Route capacity; grants a Trader unit |
| Great Library | 400 | Recorded History (civic) | Flat land adjacent to a Campus with a Library | +2 Science; +1 Great Scientist point per turn; +2 Great Work of Writing slots; boosts all Ancient and Classical era techs. R&F/GS: +1 Great Writer point per turn; random tech boost after another player recruits a Great Scientist |
| Great Lighthouse | 290 | Celestial Navigation | On Coast, adjacent to land and a Harbor with a Lighthouse | +3 Gold; +1 Great Admiral point per turn; +1 Movement for all naval units |
| Jebel Barkal (Nubia pack) | 400 | Iron Working | On a Desert Hills tile | Vanilla/R&F: awards 2 Iron. GS: awards 6 Iron per turn; +4 Faith to your cities within 6 tiles |
| Machu Picchu (GS) | 400 | Engineering | On a Mountain tile without a Volcano | +4 Gold; Mountain tiles give a standard adjacency bonus to Commercial Hub, Theater Square and Industrial Zone districts in all cities |
| Mahabodhi Temple | 400 | Theology (civic) | On Woods adjacent to a Holy Site with a Temple; religion must be founded | +4 Faith; grants 2 Apostles; GS: +2 Diplomatic Victory Points |
| Mausoleum at Halicarnassus (P&M) | 400 | Defensive Tactics (civic) | Coastal tile adjacent to a Harbor | +1 Science, +1 Faith, +1 Culture on all Coast tiles in this city; Great Engineers get +1 charge |
| Petra | 400 | Mathematics | On Desert or Floodplains without Hills | +2 Food, +2 Gold, +1 Prod on all Desert tiles of this city (non-Floodplains) |
| Statue of Zeus (B&G) | 400 | Military Training (civic) | Flat land adjacent to an Encampment with a Barracks | +3 Gold; grants 3 Spearmen, 3 Archers and a Battering Ram; +50% Prod toward anti-cavalry units (list page: across your civilization) |
| Terracotta Army | 400 | Construction | Flat Grassland/Plains adjacent to an Encampment with a Barracks or Stable | +2 Great General points per turn; all current land units gain a Promotion level; Archaeologists may enter foreign lands without Open Borders |

### Medieval
| Wonder | Prod | Requires | Placement | Effect |
|---|---|---|---|---|
| Alhambra | 710 | Castles | On Hills adjacent to an Encampment | +2 Amenities; +1 or +2 Great General points per turn [conflict: list page +1, per-wonder page +2]; +1 Military policy slot; same defensive bonuses as a Fort improvement |
| Angkor Wat (K&I) | 710 | Medieval Faires (civic) | Adjacent to an Aqueduct district | +2 Faith; +1 Population in all current cities when built; +1 Housing in all cities |
| Chichen Itza | 710 | Guilds (civic) | On Rainforest | +2 Culture and +1 Prod on all Rainforest tiles for this city |
| Hagia Sophia | 710 | Buttress (GS) / Education (Vanilla, R&F) | Flat land adjacent to a Holy Site; religion must be founded | +4 Faith; Missionaries and Apostles can spread religion 1 extra time |
| Huey Teocalli (Aztec pack) | 710 | Military Tactics | On a Lake tile adjacent to land | +1 Amenity from entertainment for each adjacent Lake tile; +1 Food and +1 Prod for each Lake tile in your empire |
| Kilwa Kisiwani (R&F+) | 710 | Machinery | Flat tile adjacent to Coast | +3 Envoys when built; as Suzerain of a city-state this city gets +15% of that city-state's yield; with 2+ Suzerainties of that type an additional +15% to all cities |
| Kotoku-in (R&F+) | 710 | Divine Right (civic) | Adjacent to a Holy Site with a Temple | +20% Faith in this city; grants 4 Warrior Monks (needs a founded religion or a majority religion) |
| Meenakshi Temple (GS) | 710 | Civil Service (civic) | Adjacent to a Holy Site; religion must be founded | +3 Faith; grants 2 Gurus; Gurus 30% cheaper to purchase; religious units adjacent to Gurus +5 Religious Strength and +1 Movement |
| Mont St. Michel | 710 | Divine Right (civic) | On Floodplains or Marsh | +2 Faith; 2 Relic slots; Apostles you create gain Martyr in addition to a second chosen ability; occupying unit +6 Defense Strength and 2 turns of fortification (per-wonder page only) |
| University of Sankore (GS) | 710 | Education | On Desert or Desert Hills adjacent to a Campus with a University | +3 Science; +1 Faith; +2 Great Scientist points per turn; +2 Science for every Trade Route to this city; domestic Trade Routes give +1 Faith to this city; other civs' Trade Routes to this city give them +1 Science and +1 Gold |

### Renaissance (five requested)
| Wonder | Prod | Requires | Placement | Effect |
|---|---|---|---|---|
| Casa de Contratacion (R&F+) | 920 | Cartography | Adjacent to a Government Plaza | +3 Great Merchant points per turn; gain 3 Governor titles; cities on your non-home continent with a Governor get +15% Prod, +15% Faith, +15% Gold |
| Forbidden City | 920 | Printing | Flat land adjacent to City Center | +5 Culture; +1 Wildcard policy slot |
| Great Zimbabwe | 920 | Banking | Adjacent to Cattle and a Commercial Hub with a Market | +5 Gold; +2 Great Merchant points per turn; +1 Trade Route capacity; this city's Trade Routes get +2 Gold for every Bonus resource in the city's territory |
| Taj Mahal (R&F+) | 920 | Humanism (civic) | Next to a River | +1 Era Score from each Historic Moment earned after completion if that moment is usually worth 2+ Era Score. (No yield effect on the page.) |
| Venetian Arsenal | 920 | Mass Production | On Coast, adjacent to an Industrial Zone | +2 Great Engineer points per turn; receive a second naval unit each time you train a naval unit (applies to any city) |

Gold purchase: wonders cannot be purchased with Gold or Faith (City page, section 8).

Sources: https://civilization.fandom.com/wiki/List_of_wonders_in_Civ6 ; https://civilization.fandom.com/wiki/Wonder_(Civ6) ; per-wonder pages https://civilization.fandom.com/wiki/<Wonder>_(Civ6) (costs, tech/civic requirement and effect text cross-checked on every wonder above).

---

## 6. UNITS

Stats from the per-unit infoboxes and the "List of units in Civ6/Unit stats" page (GS values where the page splits them). Columns: Prod = production cost; Buy = Gold purchase cost (listed on the pages; always 4x Prod, see section 8); CS = combat (melee) strength; RS = ranged strength (Bombard strength for siege); Rng = range; Mv = movement; Res = strategic resource consumed to build (20 of it, per the stats page; "-" = none); Maint = Gold per turn. n/a = not given. Upgrade targets are those on the infobox (civ-unique replacements omitted). "Obs" = tech or civic that makes the unit obsolete (can no longer be built).

### Military units
| Unit | Class | Era | Prod | Buy | CS | RS | Rng | Mv | Req tech | Res | Upgrades to | Maint | Obs / notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Warrior | Melee | Ancient | 40 | 160 | 20 | - | - | 2 | none (start) | - | Swordsman | 0 | Obs Gunpowder. +5 CS vs anti-cavalry. Free maintenance |
| Slinger | Ranged | Ancient | 35 | 140 | 5 | 15 | 1 | 2 | none (start) | - | Archer | 0 | Obs Machinery. -17 RS vs district defenses and naval units. Free maintenance |
| Archer | Ranged | Ancient | 60 | 240 | 15 | 25 | 2 | 2 | Archery | - | Crossbowman | 1 | Obs Ballistics. -17 RS vs district defenses and naval units |
| Scout | Recon | Ancient | 30 | 120 | 10 | - | - | 3 | none (start) | - | Skirmisher (GS) / Ranger | 0 | Free maintenance. +5 XP per Tribal Village, +10 XP per Natural Wonder found |
| Spearman | Anti-cavalry | Ancient | 65 | 260 | 25 | - | - | 2 | Bronze Working | - | Pikeman | 1 | Obs Metal Casting. +10 CS vs light, heavy and ranged cavalry |
| Heavy Chariot | Heavy cavalry | Ancient | 65 | 260 | 28 | - | - | 2 | Wheel | - | Knight | 1 | Obs Combustion. +1 Mv if turn starts on flat tile without Woods/Rainforest/Hills; ignores enemy zone of control. No resource listed |
| Horseman | Light cavalry | Classical | 80 | 320 | 36 | - | - | 4 | Horseback Riding | 20 Horses | Courser (GS) | 2 | Obs Synthetic Materials. Ignores zone of control |
| Swordsman | Melee | Classical | 90 | 360 | 35 | - | - | 2 | Iron Working | 20 Iron | Man-At-Arms | 2 | Obs Replaceable Parts. +5 CS vs anti-cavalry |
| Catapult | Siege | Classical | 120 | 480 | 25 | 35 (bombard) | 2 | 2 | Engineering | - | Trebuchet | 2 | Obs Steel. Bombard attack, -17 bombard strength vs land units; cannot attack after moving unless Expert Crew promotion |
| Battering Ram | Support | Ancient | 65 | 260 | none | - | - | 2 | Masonry | - | Siege Tower (GS) / Medic (Vanilla, R&F) | 1 | Obs Civil Engineering. GS: melee and anti-cavalry units attacking an adjacent district do full damage to Ancient Walls only |
| Siege Tower | Support | Classical (list page: Medieval in GS) | 100 | 400 | none | - | - | 2 | Construction (Vanilla/R&F); Machinery (GS, per unit page) | - | Medic | 2 | Obs Civil Engineering. GS: adjacent melee/anti-cavalry ignore Walls, only vs Ancient and Medieval Walls |
| Man-At-Arms | Melee | Medieval | 160 | 640 | 45 | - | - | 2 | Apprenticeship | 20 Iron | Musketman | 3 | Obs Gunpowder. +5 CS vs anti-cavalry |
| Pikeman | Anti-cavalry | Medieval | 180 (Vanilla/R&F 200) | 720 (800) | 45 | - | - | 2 | Military Tactics | - | Pike and Shot | 2 (Vanilla/R&F 3) | Obs Composites. +10 CS vs light, heavy and ranged cavalry |
| Crossbowman | Ranged | Medieval | 180 | 720 | 30 | 40 | 2 | 2 | Machinery | - | Field Cannon | 3 | Obs Advanced Ballistics. -17 RS vs district defenses and naval units |
| Knight | Heavy cavalry | Medieval | 220 (Vanilla/R&F 180) | 880 (720) | 50 | - | - | 4 | Stirrups | 20 Iron | Cuirassier (GS) / Tank | 4 (Vanilla/R&F 3) | Obs Composites. Ignores zone of control |
| Courser (GS) | Light cavalry | Medieval | 200 | 800 | 46 | - | - | 5 | Castles | 20 Horses | Cavalry | 3 | Obs Synthetic Materials. Ignores zone of control |
| Skirmisher (GS, extra) | Recon | Medieval | 150 | 600 | 20 | 30 | 1 | 3 | Machinery | - | Ranger | 2 | Upgrades from Scout |
| Trebuchet | Siege | Medieval | 200 | 800 | 35 | 45 (bombard) | 2 | 2 | Military Engineering | - | Bombard | 3 | Obs Steel. Same bombard rules as Catapult |
| Musketman | Melee | Renaissance | 240 | 960 | 55 | - | - | 2 | Gunpowder | 20 Niter | Line Infantry | 4 | Obs Advanced Ballistics. +5 CS vs anti-cavalry |
| Pike and Shot (R&F+) | Anti-cavalry | Renaissance | 250 | 1000 | 55 | - | - | 2 | Metal Casting | - | AT Crew | 4 | Obs Combined Arms. +10 CS vs light, heavy and ranged cavalry |
| Bombard | Siege | Renaissance | 280 | 1120 | 45 | 55 (bombard) | 2 | 2 | Metal Casting | 20 Niter | Artillery | 4 | Obs Guidance Systems. Same bombard rules as Catapult |
| Galley | Naval melee | Ancient | 65 | 260 | 30 | - | - | 3 | Sailing | - | Caravel | 1 | Obs Steam Power. Coast only until Cartography |
| Quadrireme | Naval ranged | Classical | 120 | 480 | 20 | 25 | 1 | 3 | Shipbuilding | - | Frigate | 2 | Obs Steel. Coast only until Cartography |
| Caravel | Naval melee | Renaissance | 240 | 960 | 55 | - | - | 4 | Cartography | - | Ironclad | 4 | Obs Combined Arms. Sight 3 |

### Civilian units
| Unit | Era | Prod | Buy | Mv | Req | Maint | Notes |
|---|---|---|---|---|---|---|---|
| Settler | Ancient | 80 base, progressive | 320 base | 2 | none | n/a (not found; blank on stats page) | Costs 1 population (city needs 2+). Prod = 30 x (x+1) + 50, x = Settlers trained incl. the initial one (page text; base listed as 80). Captured Settlers/conquered cities do not raise it, free Settlers do. Sight 3 |
| Builder | Ancient | 50 base, progressive | 200 base | 2 | none | n/a (not found; blank on stats page) | 3 build charges. Prod = 4 x (x+1) + 46, x = Builders trained or purchased. Harvest/remove-feature use 1 charge |
| Trader | Ancient | 40 base, rises with tech | 160 base | 2 | Foreign Trade (civic) | 0 | Makes and maintains one Trade Route; builds roads while travelling; Switch City action. Cost "progressive" with technological development (City page); formula n/a (not found) |

Purchase restriction (City page): a unit cannot be bought if a same-class unit already occupies the city tile (Encampment gives a second spawn tile).

Sources: https://civilization.fandom.com/wiki/List_of_units_in_Civ6 ; https://civilization.fandom.com/wiki/List_of_units_in_Civ6/Unit_stats ; https://civilization.fandom.com/wiki/List_of_units_in_Civ6/By_class ; per-unit pages https://civilization.fandom.com/wiki/<Unit>_(Civ6) (Warrior, Slinger, Archer, Scout, Spearman, Heavy_Chariot, Horseman, Swordsman, Catapult, Battering_Ram, Siege_Tower, Man-At-Arms, Pikeman, Crossbowman, Knight, Courser, Trebuchet, Musketman, Pike_and_Shot, Bombard, Settler, Builder, Trader, Galley, Quadrireme, Caravel, Skirmisher) ; https://civilization.fandom.com/wiki/City_(Civ6)

---

## 7. BUILDINGS

Prod = production cost, Maint = Gold per turn (from the per-building infobox; "n/a" = the infobox leaves the field blank and the page text does not state it; do not assume 0). "Citizen slot" = a specialist slot. Gold purchase = 4x Prod (section 8). Hierarchical requirement: a building needs the lower building of the same district (University needs Library, Temple needs Shrine, Bank needs Market, Shipyard needs Lighthouse, Armory needs Barracks or Stable). Buildings in the City Center are free-order except Walls (Ancient, then Medieval, then Renaissance). Barracks and Stable are mutually exclusive in one Encampment. A building cannot be sold or removed (Building page).

District base costs (District page): most districts 54 Prod; Aqueduct 36; Government Plaza and Diplomatic Quarter 30; Dam and Canal 81 (GS); unique districts half; formula in section 14. Government Plaza: only one per empire.

| Building | District | Prod | Maint | Requires | Effects (GS where the page splits) |
|---|---|---|---|---|---|
| Palace | City Center | n/a (capital, free) | n/a | Empire Capital | +2 Prod, +1 Culture, +2 Science, +5 Gold, +1 Housing, +2 Amenities from entertainment (Vanilla/R&F +1), +1 Great Work slot (any type), +3 Combat Strength ("Palace Guard"); R&F/GS: +1 Loyalty per turn from each citizen |
| Monument | City Center | 60 | n/a | none (start) | Vanilla: +2 Culture. R&F/GS: +1 Culture, +1 Loyalty, +1 additional Culture if the city is at maximum Loyalty |
| Granary | City Center | 65 | n/a | Pottery | +1 Food, +2 Housing |
| Water Mill | City Center | 80 | n/a | Wheel | +1 Food, +1 Prod; bonus resources improved by Farms +1 Food each; city must be adjacent to a River |
| Ancient Walls | City Center | 80 | none (no maintenance since the Summer 2017 update) | Masonry | Walls around City Center and Encampment that allow ranged strikes, must be defeated before the city can be assaulted; +100 Outer Defense Strength; +3 Combat Strength; +1 Housing under Monarchy (R&F/GS); obsolete with Steel; cannot be purchased |
| Medieval Walls | City Center | 220 (Vanilla/R&F 225) | none | Castles; Ancient Walls | +100 Outer Defense; +3 Combat Strength (total +6); +1 Housing under Monarchy (total +2); cannot be purchased with Gold |
| Renaissance Walls | City Center | 300 (Vanilla/R&F 305) | none | Siege Tactics; Medieval Walls | +100 Outer Defense; +3 Combat Strength (total +9); +1 Housing under Monarchy (total +3); GS: +2 Science with Military Research card, +2 Diplomatic Favor under Monarchy |
| Library | Campus | 90 | 1 | Writing | +2 Science; +1 citizen slot; +1 Great Scientist point/turn; (R&F: +2 Science per Scientific city-state with 3 Envoys) |
| University | Campus | 250 | 2 | Education; Library | +4 Science; +1 Housing; +1 citizen slot; +1 Great Scientist point/turn |
| Shrine | Holy Site | 70 | 1 | Astrology | +2 Faith; +1 citizen slot; +1 Great Prophet point/turn; allows buying Missionaries with Faith |
| Temple | Holy Site | 120 | 2 | Theology (civic); Shrine | +4 Faith; +1 citizen slot; +1 Great Prophet point/turn; +1 Relic slot; allows buying Apostles, Gurus, Inquisitors (and Warrior Monks with the right belief) |
| Amphitheater | Theater Square | 150 | 1 | Drama and Poetry (civic) | +2 Culture; +1 citizen slot; +1 Great Writer point/turn; +2 Great Work of Writing slots |
| Market | Commercial Hub | 120 | n/a | Currency | +3 Gold; +1 citizen slot; +1 Great Merchant point/turn; GS: +2 Gold per Trade city-state with 3 Envoys (R&F +4); R&F: +1 Trade Route capacity if the city has no Lighthouse |
| Bank | Commercial Hub | 290 | n/a | Banking; Market | +5 Gold; +1 citizen slot; +1 Great Merchant point/turn; GS: +2 Gold per Trade city-state with 6 Envoys (R&F +4) |
| Lighthouse | Harbor | 120 | n/a | Celestial Navigation | +1 Food; +1 Food on Coast and Lake tiles controlled by the city; +1 Gold; +1 Housing (GS: +2 additional Housing if City Center is adjacent to Coast or Lake); +1 citizen slot; +1 Great Admiral point/turn; +25% combat XP for naval units trained there; R&F: +1 Trade Route capacity if the city has no Market |
| Shipyard | Harbor | 290 | 2 | Mass Production; Lighthouse | +25% naval combat XP; bonus Prod equal to the district's adjacency Gold bonus; GS: +1 Prod on unimproved Coast and Lake tiles; +1 citizen slot; +1 Great Admiral point/turn |
| Workshop | Industrial Zone | 195 | 1 | Apprenticeship | +3 Prod (Vanilla/R&F +2); +1 citizen slot; +1 Great Engineer point/turn |
| Barracks | Encampment | 90 | 1 | Bronze Working | +1 Prod; +1 Housing; +1 citizen slot; +1 Great General point/turn; +25% combat XP for melee, ranged and anti-cavalry land units trained there; GS: strategic-resource stockpile +10; excludes Stable |
| Stable | Encampment | 120 | 1 | Horseback Riding | +1 Prod; +1 Housing; +1 citizen slot; +1 Great General point/turn; +25% combat XP for cavalry and siege units trained there; GS: stockpile +10; excludes Barracks |
| Armory | Encampment | 195 | 2 | Military Engineering; Barracks or Stable | +3 Prod (Vanilla/R&F +2); +1 citizen slot; +1 Great General point/turn; +25% combat XP for all land units trained there; allows training Military Engineers; GS: stockpile +10 |
| Arena | Entertainment Complex | 150 | 1 | Games and Recreation (civic) | +2 Amenities from entertainment; R&F/GS: +1 Culture, +1 Tourism after Conservation |
| Ancestral Hall (R&F+) | Government Plaza | 150 | 1 | Tier 1 government adopted (list: era Classical) | +50% Prod toward Settlers in this city; new cities get a free Builder; +1 Governor title. Mutually exclusive with Audience Chamber and Warlord's Throne |
| Audience Chamber (R&F+) | Government Plaza | 150 | 1 | Tier 1 government adopted | +2 Amenities and +4 Housing in cities with Governors; -2 Loyalty in cities without Governors; +1 Governor title. Exclusive of the other two |
| Warlord's Throne (R&F+) | Government Plaza | 150 | 1 | Tier 1 government adopted | Capturing an enemy city grants +20% Prod in all cities for 5 turns; +1 Governor title. Exclusive of the other two |
| Foreign Ministry (R&F+) | Government Plaza | 290 | 2 | Tier 2 government adopted; a Tier 1 plaza building | Leveraging city-states costs half Gold; city-state units +4 Combat Strength if you are Suzerain (incl. levied); +1 Governor title; GS: +3 Diplomatic Favor per turn. Exclusive of the other Tier 2 buildings |
| Grand Master's Chapel (R&F+) | Government Plaza | 290 | 2 | Tier 2 government adopted; a Tier 1 plaza building | Can buy land military units with Faith; pillaging improvements and districts gives bonus Faith; +1 Governor title; GS: +5 Faith |
| Intelligence Agency (R&F+) | Government Plaza | 290 | 2 | Tier 2 government adopted; a Tier 1 plaza building | +1 Spy and Spy capacity; spy operations more likely to succeed; +1 Governor title. Exclusive of the other Tier 2 buildings |

Notes: Commercial Hub and Harbor districts pay their own upkeep from their Gold yields; every other specialty district has per-turn Gold maintenance (Gold page); infobox values read: Campus 1, Theater Square 1, Holy Site 1, Industrial Zone 1 (other districts n/a).

Sources: https://civilization.fandom.com/wiki/List_of_buildings_in_Civ6 ; https://civilization.fandom.com/wiki/Building_(Civ6) ; https://civilization.fandom.com/wiki/District_(Civ6) ; per-building pages https://civilization.fandom.com/wiki/<Building>_(Civ6) (Monument, Granary, Water_Mill, Ancient_Walls, Medieval_Walls, Renaissance_Walls, Palace, Library, University, Shrine, Temple, Amphitheater, Market, Bank, Lighthouse, Shipyard, Workshop, Barracks, Stable, Armory, Arena, Ancestral_Hall, Audience_Chamber, Warlord's_Throne, Foreign_Ministry, Grand_Master's_Chapel, Intelligence_Agency).

---

## 8. GOLD: purchasing, maintenance, bankruptcy, upgrades

### 8.1 Purchase cost
| Rule | Value / text (source page) |
|---|---|
| Gold price of a unit or building | 4 x its current Production cost (City page: "in general"). Confirmed by every unit row in section 6 (e.g. Warrior 40 -> 160, Spearman 65 -> 260, Bombard 280 -> 1120) |
| Faith price | 2 x Production cost (City page) |
| Currency equivalences | Gold page: 1 Gold = 0.25 Production = 0.5 Faith. Faith page: 1 Faith = 0.5 Production = 2 Gold |
| Discounts on Production cost (policies etc.) | do NOT reduce the purchase price (City page) |
| How already-invested Production changes the price | n/a (not found). The pages say "current Production cost" only |
| Civilian units (Settler, Builder) | Purchase price rises with each unit produced OR purchased, same scaling as production (Settler Prod = 30 x (x+1) + 50; Builder Prod = 4 x (x+1) + 46); Traders scale with tech progress; buying raises the price just like building |
| Buildings | Bought with Gold from any unlocked district; appear instantly and work immediately; buying many buildings does not raise their price (Faith page). Cannot be bought at all: city defenses (Ancient/Medieval/Renaissance Walls), Government Plaza buildings (R&F), wonders |
| Units | Appear instantly but with no Movement (usable next turn). Cannot be bought if another unit of the same class occupies the spawn tile (a district such as Encampment gives a second spawn tile). Spy and a few special units cannot be bought with Gold |
| Districts | Vanilla: cannot be purchased. R&F: Gold purchase only in a city with Governor Reyna's Contractor title. GS: Faith purchase only with Governor Moksha's Divine Architect title (District page: "districts generally cannot be purchased with Gold") |
| Wonders | Cannot be purchased (City page). The page notes only that harvesting resources in the city's territory can speed wonder production |
| Corps / Army | Units trained as Corps/Fleet cost 150% Production/Gold; Army/Armada 225% (Unit page). City page says the PURCHASE price of a Corps is double and an Army triple. [conflict] Nationalism / Mobilization civics, out of era |
| Tile purchase | Gold; only tiles adjacent to your borders and at most 3 hexes from a City Center; price rises with distance and with tech/civic progress; exact formula n/a (not found). Land Surveyors card: -20% |

Discounts to Gold purchases from government (section 3): Merchant Republic 15% (Vanilla), Democracy 15% (GS; 25% in R&F); legacy bonuses +1% per 15 turns (Vanilla). Theocracy gives 15% off Faith purchases.

### 8.2 Faith purchasing (default rules)
Faith price 2 x Production. By default Faith buys: religious units (Missionary 150, Apostle 400, Inquisitor 75, Guru 240 Faith; each subsequent purchase raises the price except Warrior Monk, fixed 200), Naturalists, Rock Bands, Great People via patronage (Oracle: -25% Faith), Tier-3 worship buildings (with the right belief). Land military units can be bought with Faith only via Theocracy (Vanilla) or the Grand Master's Chapel (R&F/GS) per the Faith page; Indonesia (Gitarja) naval units; Monumentality dedication (R&F) civilians. [conflict] City page still says Theocracy allows land-unit Faith purchases in all versions.

### 8.3 Unit maintenance
| Item | Value |
|---|---|
| When paid | Automatically from the treasury every turn (Gold page / Unit page) |
| Free units | Warrior, Slinger, Scout (and Sumeria's War-Cart) need no maintenance; Trader maintenance 0. No empire-wide free allowance is stated anywhere: n/a (not found) |
| Gold per unit per turn (GS) | 0: Warrior, Slinger, Scout, Trader. 1: Archer, Spearman, Heavy Chariot, Galley, Battering Ram. 2: Horseman, Swordsman, Catapult, Quadrireme, Siege Tower, Pikeman, Skirmisher, Military Engineer. 3: Man-At-Arms, Crossbowman, Courser, Trebuchet. 4: Knight, Musketman, Pike and Shot, Bombard, Caravel. (Vanilla/R&F differences: Pikeman 3, Knight 3, Military Engineer 4.) Gold page: Spearman 1 ... Giant Death Robot 15 |
| Scaling | Maintenance rises with unit era (Gold page: "usually scale with the game era") |
| Reducing policies | Conscription: -1 Gold per unit (Ancient card); Levee en Masse: -2 Gold per unit (Modern) |
| Combined units | Corps/Fleet maintenance 150% of one base unit, Army/Armada 200% (Unit page) |
| Strategic resources | GS: late-game units also consume Coal/Oil/Aluminum/Uranium per turn (not in this era range) |

### 8.4 Negative gold

- Gold flow can be negative. If the treasury becomes empty, units DISBAND automatically (permanently removed) until the balance is restored (Unit page). Which units go first: n/a (not found).
- Amenities page ("Bankruptcy"): whenever the treasury is at 0 and Gold flow is negative, citizens are discontented: -1 Amenity per 10 Gold of negative flow.

### 8.5 Unit upgrades
| Item | Value |
|---|---|
| Conditions | Unit must be in friendly territory, have more than 0 Movement, and you must have the Gold. Upgrade button appears in the unit's command tab. Units do not heal on upgrading; they keep promotions and XP |
| Strategic resource | GS: needs the same amount of the new unit's resource as producing it would (e.g. 20 Iron), unless the old unit needs the same resource. Other rulesets: only 1 of the resource |
| Gold cost formula | n/a (not found). The Unit page says only that the price "usually reflects how much its strength will increase" and is higher in later eras. The only listed data point: upgrading a Slinger (35 Prod) to an Archer (60 Prod) costs 60 Gold on Standard speed (Slinger and Archer pages), (derived: 60 Gold / 25 Prod difference = 2.4 Gold per Production, a single point, not a stated rule) |
| Patches | Winter 2016 update: lowered the minimum upgrade cost. April 2019 (Antarctic Late Summer) update: upgrade costs +~33% |
| Corps / Army | Upgrade price doubles for a Corps/Fleet, triples for an Army/Armada (also applies to the resource cost in GS) |
| Discount cards | Professional Army (Mercenaries): 50% Gold discount (Vanilla/R&F: 50% discount on all upgrades). Retinues (Mercenaries, GS): 50% resource discount only. Force Modernization (Urbanization, GS): 50% Gold AND resource discount (replaces both) |

### 8.6 Building and district maintenance

- Building and district maintenance is fixed (Gold page). Per-building values are in section 7 (Library 1, University 2, Shrine 1, Temple 2, Amphitheater 1, Arena 1, Barracks 1, Stable 1, Armory 2, Workshop 1, Shipyard 2, Government Plaza T1 1 / T2 2); Walls have no maintenance (Summer 2017 update); Monument, Granary, Water Mill, Market, Bank, Lighthouse: n/a (not listed).
- Specialty districts cost Gold maintenance except the Commercial Hub and Harbor, which pay their own upkeep from the Gold they produce (Gold page). District infobox maintenance: Campus 1, Theater Square 1, Holy Site 1, Industrial Zone 1 (n/a for the others read).

Sources: https://civilization.fandom.com/wiki/Gold_(Civ6) (redirects to Gold_(currency)_(Civ6); also covers Maintenance) ; https://civilization.fandom.com/wiki/City_(Civ6) (Purchasing section) ; https://civilization.fandom.com/wiki/Unit_(Civ6) (maintenance, upgrades; the pages Upgrade_(Civ6) and Maintenance_(Civ6) redirect to these) ; https://civilization.fandom.com/wiki/Amenities_(Civ6) ; https://civilization.fandom.com/wiki/Faith_(Civ6) ; https://civilization.fandom.com/wiki/District_(Civ6) ; https://civilization.fandom.com/wiki/Professional_Army_(Civ6), /Retinues_(Civ6), /Force_Modernization_(Civ6) ; https://civilization.fandom.com/wiki/Civilization_VI_April_2019_Update ; https://civilization.fandom.com/wiki/Civilization_VI_Winter_2016_Update ; https://civilization.fandom.com/wiki/Slinger_(Civ6), /Archer_(Civ6). The dedicated page Purchasing_(Civ6) does not exist.

---

## 9. SCIENCE and CULTURE base yields

| Item | Value (page) |
|---|---|
| Science per citizen | 0.5 Science per Citizen, with or without a Campus (since the February 7, 2018 update; Science page) |
| Culture per citizen | 0.3 Culture per Citizen (Culture page) |
| Palace (City Center building, capital only) | +2 Science, +1 Culture, +2 Prod, +5 Gold, +1 Housing, +2 Amenities from entertainment (GS), +3 Combat Strength, 1 Great Work slot (Palace infobox / buildings list) |
| Monument | Vanilla +2 Culture; R&F/GS +1 Culture, +1 Loyalty, +1 more Culture at max Loyalty (section 7) |
| Campus district | Science from adjacency; each specialist +2 Science; +1 Great Scientist point/turn |
| Library / University / (Research Lab) | +2 / +4 / (+5) Science (Science page) |
| Theater Square district | Culture from adjacency; each specialist +2 Culture; +1 Great Writer, +1 Great Artist, +1 Great Musician point/turn |
| Amphitheater | +2 Culture; Art Museum and Archaeological Museum +2 Culture each; Broadcast Center +4 (Culture page) |
| Campus adjacency (GS) | +1 per adjacent Mountain; +2 per adjacent Great Barrier Reef, Reef or Geothermal Fissure, Pamukkale; +0.5 per adjacent Rainforest and per adjacent district tile |
| Theater Square adjacency | R&F/GS +2 per adjacent wonder (Vanilla +1); GS +2 per adjacent Entertainment Complex or Water Park, +2 Pamukkale; +0.5 per adjacent district tile |
| Other adjacency (for reference) | Holy Site +2 natural wonder, +1 Mountain, +0.5 per Woods and per district; Commercial Hub +2 river, +2 per adjacent Harbor, +0.5 district; Harbor +2 City Center, +1 per sea resource, +0.5 district; Industrial Zone Vanilla/R&F +1 per adjacent Mine or Quarry, +0.5 per district; GS infobox +1 per Quarry, +1 per strategic resource, +0.5 per Mine or Lumber Mill, +0.5 per district, +2 per Aqueduct/Bath/Canal/Dam |
| Per-specialist yields | Campus +2 Science; Theater Square +2 Culture; Holy Site +2 Faith; Commercial Hub +4 Gold; Industrial Zone +2 Prod; Harbor +2 Gold and +1 Food |
| Policies that scale them | Natural Philosophy +100% Campus adjacency, Aesthetics +100% Theater Square adjacency, Scripture +100% Holy Site adjacency (section 4) |
| Boosts | Eureka/Inspiration give 50% (40% from R&F on, so 40% in GS) of the cost (section 14) |

Sources: https://civilization.fandom.com/wiki/Science_(Civ6) ; https://civilization.fandom.com/wiki/Culture_(Civ6) ; https://civilization.fandom.com/wiki/Campus_(Civ6), /Theater_Square_(Civ6), /Holy_Site_(Civ6), /Commercial_Hub_(Civ6), /Harbor_(Civ6), /Industrial_Zone_(Civ6) ; https://civilization.fandom.com/wiki/Palace_(Civ6)

---

## 10. TRADE ROUTES

### Creation and capacity
| Item | Rule (Trade Route / Trader / Trading Post pages) |
|---|---|
| Requirements | Free Trading Capacity of at least 1, a free Trader, and at least 1 valid destination |
| Unlock | Foreign Trade civic (unlocks the Trader unit, 40 Prod / 160 Gold, maintenance 0) and grants Trading Capacity 1 |
| Capacity sources | Foreign Trade +1. Each city with a Commercial Hub or Harbor adds 1 (R&F onward: a Market or Lighthouse instead; Vanilla text: Commercial Hub or Harbor). A city with both adds only 1, not 2. Colossus +1; Great Zimbabwe +1; Merchant Republic +2 (Vanilla only); Great Merchants Zhang Qian, Ibn Fadlan, Marco Polo, Melitta Bentz +1 each; GS Great Admiral Zheng He +1 when retired. Exceeding capacity after a loss: existing routes stay active, new Traders go idle |
| One trader = one route | A Trader services a single route; when Traders equal capacity you cannot build more |
| Origin / destination | Route runs City Center to City Center. All benefits go to the ORIGIN city (move the Trader there first, "Switch City" takes a turn). Destination can be your own city, a foreign city or a city-state; you must have discovered it, not be at war with its owner, and it must be in range with a valid path. Only one route may exist between cities A and B at a time. Free Cities are not valid destinations |
| Sea routes | Coast tiles need Celestial Navigation (or Shipbuilding, which lets all land units embark); Ocean tiles need Cartography; both cities need maritime access (coastal or Harbor) |
| Range | Land 15 tiles; sea 30 tiles; cannot be raised by technology. Trading Posts reset range (see below). No change by era |
| Speed | 1 tile per turn on land and sea |
| Trading Post | Created in origin and destination City Centers when a route completes its duration the first time (Mongolia on start, Rome on city founding). A route passing through a city with your Trading Post can continue another 15 tiles from it; each Trading Post a route passes through adds +1 Gold to that route |

### Duration

- Standard speed: a route lasts a minimum of 21 turns and ends only when the Trader is back at the origin city after a full round trip. Round trip = 2 x distance turns (1 tile per turn). Duration = whole number of round trips, enough to reach the minimum. Examples (page): distance 4 -> 8-turn round trip, 3 trips, 24 turns; 6 -> 12, 2 trips, 24; 10 -> 20, 2 trips, 40; 11 -> 22, 1 trip, 22; 15 -> 30, 1 trip, 30.
- GS: the current WORLD era adds turns to the minimum duration (TradeRouteMinimumEndTurnChange): Ancient/Classical +0; Medieval/Renaissance +10 (50% longer); Industrial/Modern/Atomic +20; Information/Future +30.
- Speed setting changes duration (page says only "dependent on game speed"; other speeds n/a).

### Yields (the district rule)

Every district present in the DESTINATION city's territory (including the City Center) adds the following to the route. Unique districts yield the same as the generic one. Whether duplicate copies of the same district stack: n/a (not stated).

| District at destination | Domestic route | International route |
|---|---|---|
| City Center | 1 Food, 1 Prod | 3 Gold |
| Campus | 1 Food | 1 Science |
| Holy Site | 1 Food | 1 Faith |
| Encampment | 1 Prod | 1 Prod |
| Commercial Hub | 1 Prod | 3 Gold |
| Theater Square | 1 Food | 1 Culture |
| Entertainment Complex | 1 Food | 1 Food |
| Water Park | 1 Food | 1 Food |
| Harbor | 1 Prod | 3 Gold |
| Industrial Zone | 1 Prod | 1 Prod |
| Government Plaza | 1 Food, 1 Prod | 2 Gold |
| Diplomatic Quarter | 1 Food, 1 Prod | 1 Culture |

Domestic routes give mainly Food and Prod; international (foreign civ or city-state) give Gold plus Science/Culture/Faith/Prod/Food depending on destination districts. Yields apply from the turn the route is established. Route also: religious pressure 0.5 each way; +1 level diplomatic visibility and +25% Tourism toward you for international routes to civs; roads built along land routes.

Boosters in range: Trading Post +1 Gold per post passed; GS water/Canal/Railroad tiles give 2 "efficiency" points per tile and Mountain Tunnel/Qhapaq Nan tiles 15, bonus = points / distance as a % of the base Gold yield, capped at +100%. Wonders: Great Zimbabwe +2 Gold per Bonus resource (routes from its city); Torre de Belem +2 Gold per Luxury at the destination; University of Sankore (+1 Science, +1 Gold foreign / +1 Faith domestic for routes to the city). Cards: Caravansaries +2 Gold (all routes); Triangular Trade +4 Gold, +1 Faith (all routes); Trade Confederation +1 Culture, +1 Science (international); Wisselbanken +2 Food, +2 Prod (Ally cities, GS also Suzerain city-states). Governors: Reyna (Foreign Exchange; Land Acquisition in GS) +3 Gold for every foreign route that ends or passes through her city; Magnus (Surplus Logistics) +2 Food to the origin city of a domestic route that ends in his city. Policy list for later cards: Market Economy, Ecommerce (out of era).

### Plunder

- Barbarians and units of civilizations at war with you can plunder a route when they enter a tile where your Trader currently is: it destroys the Trader and gives the plundering owner Gold (amount: n/a (not found)). Plundering costs the unit's remaining Movement (it can move then plunder). Total War card (Industrial) +50% plunder rewards.
- When war is declared, all routes between the two civs are cancelled and the Traders return to origin to be reassigned (not lost). Routes are not cancelled if they merely run through hostile territory. Routes also end if the destination/origin becomes a Free City.

Sources: https://civilization.fandom.com/wiki/Trade_route_(Civ6) ; https://civilization.fandom.com/wiki/Trader_(Civ6) ; https://civilization.fandom.com/wiki/Trading_Post_(Civ6) ; https://civilization.fandom.com/wiki/Commercial_Hub_(Civ6), /Harbor_(Civ6).

---

## 11. LOYALTY (Rise and Fall / Gathering Storm)

Not in vanilla; added in R&F. Each city has a Loyalty score 0-100 and a per-turn change equal to the sum of four factors: pressure from nearby citizens, Governors, happiness (Amenities), other factors. Starting Loyalty of a new city and the exact per-turn update rule on the score: n/a (not found).

### Loyalty bands
| Band | Loyalty | Effect |
|---|---|---|
| Loyal | 76-100 | none |
| Wavering Loyalty | 51-75 | 75% Population growth; -25% to all yields |
| Disloyal | 26-50 | 25% Population growth; -50% to all yields |
| Unrest | 1-25 | no Population growth; -100% to all yields (city non-functional) |
| Revolt | 0 or less while still receiving negative Loyalty per turn | City rebels and becomes a Free City |

### Pressure from nearby citizens (formula from the page)

- Only cities within 9 tiles count. Free Cities and city-states exert no pressure. Pressure per Population falls 10% per tile of distance.
- Domestic = Age Factor x sum over own cities in range of [ Population x (10 - Distance) ]; a city's own pressure uses Distance 0.
- Foreign = Age Factor of the foreign civ x sum over foreign cities in range of [ Population x (10 - Distance) ].
- Age Factor: 1.0 Normal Age, 0.5 Dark Age, 1.5 Golden or Heroic Age. Each citizen in the Capital exerts an additional 1.0 per turn regardless of Age.
- Pressure from Nearby Citizens = 10 x (Domestic - Foreign) / (min[Domestic, Foreign] + 0.5), capped to +/-20 per turn. Other factors then add on, so the total can exceed +/-20.
- Bread and Circuses project (Entertainment Complex/Water Park) doubles the Population count of that city for this calculation. Cultural dominance: your citizens exert 25% more pressure. Worked example on the page: Domestic 31, Foreign 45 -> pressure -4.4.

### Other per-turn terms
| Source | Loyalty per turn |
|---|---|
| Happiness (Amenities) | Unhappy or worse (deficit 3+): -6. Displeased (deficit 1-2): -3. Happy (surplus 1-2; GS 3-4): +3. Ecstatic (surplus 3+; GS 5+): +6 |
| Any Governor assigned to the city (active from assignment) | +8 |
| Governors Amani and Victor | Amani with Prestige title in another city or city-state within 9 tiles +2; another civ's Amani with Emissary title within 9 tiles -2; Victor with Garrison Commander title in the city or a city within 9 tiles +4 |
| Monument | +1 |
| Government Plaza (district built in city) | +8 |
| Audience Chamber, city without Governor | -2 |
| Colosseum within 6 tiles | +2 |
| Palace (R&F/GS) | +1 Loyalty per turn from each Citizen (Palace infobox text) |
| Garrison | Limitanei card +2 if garrisoned; Martial Law (Industrial) +2 (GS +4) if garrisoned; Occupied city -5, which a garrisoned unit negates |
| Policy cards | Praetorium +2 (city with Governor); Communications Office +1 to +6 (city with Governor); Colonial Offices +3 (city not on capital's continent); Retainers gives +1 Amenity to garrisoned cities (feeds the happiness term); Police State -2 (R&F); Automated Workforce -5 |
| Religion | +3 if the city follows the religion you founded; -3 if you founded a religion and the city does not follow it |
| Starvation | -4 if the city is starving (e.g. Farms pillaged) |
| Conquered cities | Variable penalty from Grievances toward the founder |
| Base levels | Free Cities +10, city-states +20 |
| Statue of Liberty | Cities within 6 tiles locked at 100 (R&F/GS) |

Where wonders and buildings touch Loyalty on the pages read: Colosseum (+2 Loyalty to each City Center within 6 tiles, R&F+), Monument, Government Plaza and Audience Chamber, Palace. Governor titles come with the civics in section 2.

### Free City

- A city whose Loyalty reaches 0 while still receiving negative pressure declares independence and becomes a Free City (dark gray/dark red). It is always at war with everyone (like Barbarians), spawns and trains military units nonstop (unit tech level = era of its last owner), is not a valid Trade Route destination, cannot be negotiated with, gives no city-state benefits, and still feels Loyalty pressure.
- A Free City petitions to join the civ that exerts the most pressure ("flipping"). Accepting: city joins with its population, buildings and districts, spawned units are disbanded, no penalty. Rejecting: it stays free and you can no longer pressure it.
- A Free City can also be captured or liberated to its original owner (improves relations, lowers Grievances, +Diplomatic Favor in GS); liberated cities are immune to pressure from the liberator.
- A Capital cannot be razed; it can in principle flip given enough pressure.

Sources: https://civilization.fandom.com/wiki/Loyalty_(Civ6) (contains the Free City section; Free_City_(Civ6) redirects there) ; https://civilization.fandom.com/wiki/Colosseum_(Civ6) ; https://civilization.fandom.com/wiki/Monument_(Civ6) ; https://civilization.fandom.com/wiki/Palace_(Civ6).

---

## 12. AMENITIES (brief)

| Item | Value (Amenities page) |
|---|---|
| Amenities needed per city | Vanilla/R&F: ceil(Population / 2 - 1) (first 2 citizens free; pop 5-6 needs 2; 11-12 needs 5). GS: ceil(Population / 2) (cities no longer start with a free Amenity except the Capital; pop 5-6 needs 3; 11-12 needs 6) |
| Satisfaction bands, GS (surplus = Amenities minus needed) | Ecstatic surplus 5+: all yields +20%. Happy 3-4: all yields +10%. Content 0-2: no change. Displeased deficit 1-2: non-Food yields -10%, growth -15%. Unhappy deficit 3-4: non-Food -20%, growth -30%. Unrest deficit 5-6: non-Food -30%, Rebels occasionally appear. Revolt deficit 7+: non-Food -40%, Rebels frequent |
| Satisfaction bands, Vanilla/R&F | Ecstatic +3: non-Food +10%, growth +20%. Happy +1-2: non-Food +5%, growth +10%. Displeased -1-2: non-Food -5%, growth -15%. Unhappy -3-4: non-Food -10%, growth -30%. Unrest -5-6: non-Food -30%, Rebels. Revolt -7+: non-Food -60%, more Rebels |
| Luxury resources | Each distinct luxury gives +1 Amenity to up to 4 cities (6 for a few special sources); duplicates do not extend reach |
| Entertainment Complex district | +1 Amenity; Arena +2 Amenities (Classical, Games and Recreation); Colosseum wonder +3 to all cities within 6 tiles (R&F/GS: +2) |
| Other sources in era | Palace +1 (GS +2); Alhambra +2; Classical Republic +1 per city with a district; Retainers +1 (garrisoned city); Civil Prestige +1; Temple of Artemis; Huey Teocalli; Great Bath +1 from entertainment; Audience Chamber +2 in cities with Governors |
| Negative | War weariness; Bankruptcy: -1 per 10 Gold of negative flow when the treasury is 0; Police State -1 (Vanilla/R&F) |
| Effect on loyalty | R&F/GS: Amenity state shifts Loyalty per turn (section 11) |

Sources: https://civilization.fandom.com/wiki/Amenities_(Civ6) ; https://civilization.fandom.com/wiki/Arena_(Civ6) ; https://civilization.fandom.com/wiki/Colosseum_(Civ6)

---

## 13. FAITH and RELIGION (brief)

### Pantheon and religion
| Item | Rule |
|---|---|
| Pantheon cost | 25 Faith on Standard speed, the same for every civ regardless of how many pantheons exist; the game prompts automatically once you have more than 25 Faith (Faith / Pantheon pages). A pantheon stays with you even if foreign religions convert your cities |
| Founding a religion | Needs a pantheon first, then a Great Prophet (earned via Great Prophet points from Holy Sites, Revelation card +2/turn, or granted free by Stonehenge). Found it in a Holy Site or on Stonehenge (a Prophet may use Stonehenge instead of a Holy Site); that city becomes the Holy City. Unused Great Prophet points after you hold a Prophet convert to Faith 1:1 |
| Limit | Number of religions = half the default player count + 1: Duel 2, Tiny 3, Small 4, Standard 5, Large 6, Huge 7. When the limit is reached no more Prophets can be recruited and Revelation goes obsolete |
| Majority religion | More than 50% of a city's citizens; city growth adds 50 pressure to its majority religion (or to atheist/pantheon pressure) |
| Great Prophet point threshold, Faith cost of a Great Prophet | n/a (not found on the pages read) |

### Faith purchasing
| What | Faith cost / condition |
|---|---|
| Religious units (after founding or converting a Holy Site city) | Missionary 150, Apostle 400, Inquisitor 75, Guru 240; price rises with each successive purchase; Warrior Monk fixed 200 (needs the Warrior Monks belief) |
| Land military units | Vanilla: with the Theocracy government. R&F/GS: with the Grand Master's Chapel built (Faith page; the City page still mentions Theocracy). Price = 2 x Production |
| Great People | Patronage with Faith at any time (Oracle -25% Faith) |
| Tier 3 worship buildings | Faith if the religion has the matching belief |
| Special | Naturalists, Rock Bands only with Faith; Monumentality dedication (R&F) lets civilians be bought with Faith; Gitarja (Indonesia) naval units; GS Moksha's Divine Architect title: whole districts with Faith |
| Conversion factor | 1 Faith = 0.5 Production = 2 Gold |
| Faith sources early | Shrine +2, Temple +4, Holy Site specialist +2, God King +1 in Capital, Stonehenge +2, Mahabodhi Temple +4, Oracle +1, luxuries Dyes/Incense/Pearls/Tobacco +1, Holy Site adjacency (section 9) |

### Pantheon beliefs (GS values, Pantheon list page)

Yield or adjacency based:

| Pantheon | Effect |
|---|---|
| Dance of the Aurora | Holy Site +1 Faith per adjacent Tundra tile |
| Desert Folklore | Holy Site +1 Faith per adjacent Desert tile |
| Sacred Path | Holy Site +1 Faith per adjacent Rainforest tile |
| River Goddess | GS: +2 Amenities and +2 Housing in cities whose Holy Site is adjacent to a River (R&F +1 Amenity) |
| Stone Circles | +2 Faith from Quarries |
| Religious Idols | +2 Faith from Mines over Luxury and Bonus resources |
| Earth Goddess | GS: +1 Faith from tiles with Breathtaking Appeal (Vanilla/R&F: Charming or Breathtaking) |
| Fire Goddess (GS) | +2 Faith from Geothermal Fissures and Volcanic Soil |
| God of Craftsmen | GS: +1 Prod and +1 Faith from improved Strategic resources (Vanilla/R&F: +1 Prod from Mines over improved Strategic resources) |
| God of the Open Sky | +1 Culture from Pastures |
| God of the Sea | +1 Prod from Fishing Boats |
| Goddess of Festivals | GS: +1 Culture from Plantations (Vanilla/R&F: +1 Food from Wine, Incense, Cocoa, Tobacco, (R&F Olives,) Coffee, Tea Plantations) |
| Goddess of the Hunt | GS: +1 Food and +1 Prod from Camps (Vanilla/R&F +1 Food) |
| Lady of the Reeds and Marshes | GS: +2 Prod from Marsh, Oasis and Desert Floodplains (earlier +1) |
| Oral Tradition | +1 Culture from Banana, Citrus, Cotton, Dyes, Silk, Spices, Sugar Plantations (removed in the June 2019 update per the Pantheon page) |
| Goddess of the Harvest | Harvesting a resource or removing a feature gives Faith equal to the other yield (removed in the June 2019 update per the Pantheon page) |

Other (non-adjacency) pantheons: City Patron Goddess +25% Prod toward districts in cities without a specialty district; Divine Spark +1 Great Person point from Holy Sites, Campuses with a Library, Theater Squares with an Amphitheater (GS); Fertility Rites +10% city growth (GS: + a free Builder); Religious Settlements +15% border expansion (GS: + a free Settler); God of Healing +30 healing in/adjacent to Holy Sites; God of the Forge +25% Prod toward Ancient/Classical military units; Monument to the Gods +15% Prod toward Ancient/Classical wonders; God of War Faith = 50% of the strength of units killed within 8 tiles of a Holy Site; Initiation Rites +50 Faith per cleared Barbarian Outpost (GS: +100 HP heal for the clearing unit).

Sources: https://civilization.fandom.com/wiki/Faith_(Civ6) ; https://civilization.fandom.com/wiki/Pantheon_(Civ6) ; https://civilization.fandom.com/wiki/List_of_pantheons_in_Civ6 ; https://civilization.fandom.com/wiki/Religion_(Civ6) ; https://civilization.fandom.com/wiki/City_(Civ6)

---

## 14. ERA COST SCALING

### Techs and civics (base costs, Standard speed)
| Era | Tech cost range | Civic cost range (Vanilla/R&F -> GS) |
|---|---|---|
| Ancient | 25 (Pottery, Animal Husbandry, Mining), 50, 80 | 20 (Code of Laws), 40, 50, 70 |
| Classical | 120, 200 | 110, 120, 175 |
| Medieval | 300, 390 | 200->220, 275->300, 290->340, 385->420 |
| Renaissance | 540->600 (first row), 660->730 (second row); Vanilla/R&F -> GS | 400->440, 540->600, 655->720 |

Tech costs grow roughly: 25/50/80 -> 120/200 -> 300/390 -> 600/730 (GS Renaissance). Page statement: tech range from 25 to 2600 Science overall; civic costs run 20 to 3500 (Future Civic).

- World-era modifier (R&F/GS, Technology, Civic and Era pages): techs and civics from eras BEFORE the current World Era cost 20% less; those from eras AFTER it cost 20% more.
- Eureka/Inspiration: 50% of cost in Vanilla, 40% from R&F on (GS therefore 40%); +10% for China (Eureka)/the Free Inquiry or Pen, Brush and Voice dedications; Babylon gets the full remaining cost on a Eureka. Boosts can be earned once, at any time until the tech/civic is done. No boost for Pottery, Animal Husbandry, Mining, Code of Laws.

### Districts

District cost = [1 + 9 x max(T, C)] x base_cost, T = fraction of the tech tree researched (0 to 1), C = fraction of the civic tree researched. So the price rises by a factor of 10 over a full game. Base costs: most districts 54; Aqueduct 36; Government Plaza and Diplomatic Quarter 30; Dam and Canal (GS) 81; Spaceport 1800 and does not scale; unique districts half of the district they replace (Roman Bath 18). Cost is locked in when the district is placed. Discount: the district types you have built least often get 40% off (25% for Government Plaza and Diplomatic Quarter). Examples derived from the formula (not on the page): max(T,C)=0.25 gives 54 x 3.25 = 175.5; 0.5 gives 297; 1.0 gives 540.

### Units, buildings, wonders by era (values from sections 5 to 7)
| Series | Ancient | Classical | Medieval | Renaissance |
|---|---|---|---|---|
| Melee line (Prod) | Warrior 40 | Swordsman 90 | Man-At-Arms 160 | Musketman 240 |
| Anti-cavalry | Spearman 65 | - | Pikeman 180 (200 V/R&F) | Pike and Shot 250 (R&F+) |
| Ranged | Slinger 35, Archer 60 | - | Crossbowman 180 | (Field Cannon later) |
| Heavy cavalry | Heavy Chariot 65 | - | Knight 220 (180 V/R&F) | Cuirassier 330 (Industrial in GS) |
| Light cavalry | - | Horseman 80 | Courser 200 (GS) | - |
| Siege | - | Catapult 120 | Trebuchet 200 | Bombard 280 |
| Naval melee / ranged | Galley 65 | Quadrireme 120 | - | Caravel 240 |
| Maintenance (Gold/turn) | 0-1 | 2 | 2-4 | 4 |
| Walls | Ancient 80 | - | Medieval 220 | Renaissance 300 |
| Campus line | Library 90 | - | University 250 | - |
| Commercial line | - | Market 120 | - | Bank 290 |
| Encampment | Barracks 90 | Stable 120 | Armory 195 | - |
| Wonders | 180 to 290 | 290 to 400 | 710 | 920 |

Unit Gold price is 4x Production in every era; no documented per-era unit-cost formula exists on the pages read (units' Production costs are fixed values per unit; only civilians scale, see section 6). Building and wonder costs are fixed per item (City page).

Sources: https://civilization.fandom.com/wiki/Technology_(Civ6) ; https://civilization.fandom.com/wiki/Civic_(Civ6) ; https://civilization.fandom.com/wiki/Era_(Civ6) ; https://civilization.fandom.com/wiki/Boost_(Civ6) ; https://civilization.fandom.com/wiki/District_(Civ6) ; https://civilization.fandom.com/wiki/City_(Civ6) ; https://civilization.fandom.com/wiki/List_of_units_in_Civ6/Unit_stats ; sections 1, 2, 5, 6, 7 of this file.

---

## APPENDIX: items not found or in conflict on the wiki

- Unit upgrade Gold formula: not on any page read (one data point: Slinger to Archer = 60 Gold).
- Free maintenance allowance (per empire): none stated; only Warrior, Slinger, Scout, Trader are free.
- How invested Production reduces the Gold purchase price; exact tile purchase price formula; Trader Production cost progression formula; plunder reward amount; starting Loyalty of a new city; Great Prophet point threshold; maintenance for Monument, Granary, Water Mill, Market, Bank, Lighthouse, Palace (infobox blank).
- Conflicts: Renaissance tech cost in Vanilla/R&F (540 on the list page, 490 on per-tech pages; 600 for GS on both); Siege Tower tech (Construction on tech list vs Machinery in GS on its own page); Education/Military Engineering cost (390 list vs 335 per-tech page); Cartography/Mass Production prerequisites (list vs per-tech page); Urban Planning obsoleted by The Enlightenment (card page) vs superseded by Colonial Offices (policy list); Native Conquest civic (Exploration on civics list vs Colonialism); Alhambra Great General points (+1 list vs +2 per-wonder); Corps purchase price (2x vs 150%); Theocracy land-unit Faith purchase in R&F/GS; Merchant Republic era; Craftsmen and Colonial Offices card types in GS.
- Not read (not requested): Governor pages, Great People point thresholds.
