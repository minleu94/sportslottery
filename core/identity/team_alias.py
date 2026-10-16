#!/usr/bin/env python3
"""Canonical Team Registry and Alias Normalization.

Maps Chinese names, English names, abbreviations, and Playsport team IDs
to unique CanonicalTeam entities across MLB, Soccer, NFL, NBA, NPB, CPBL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass(frozen=True)
class CanonicalTeam:
    canonical_id: str          # e.g. 'MLB_CHC'
    sport: str                 # 'baseball', 'soccer', 'football', 'basketball'
    league: str                # 'MLB', 'PREMIER', 'NFL', 'NBA', 'CPBL', 'NPB'
    abbreviation: str          # e.g. 'CHC'
    display_name_en: str       # e.g. 'Chicago Cubs'
    display_name_zh: str       # e.g. '芝加哥小熊'
    short_name_zh: str         # e.g. '小熊'
    aliases: List[str] = field(default_factory=list)
    playsport_team_id: Optional[str] = None


# =========================================================================
# MLB Registry (All 30 Teams)
# =========================================================================
MLB_TEAMS: List[CanonicalTeam] = [
    CanonicalTeam("MLB_ARI", "baseball", "MLB", "ARI", "Arizona Diamondbacks", "亞利桑那響尾蛇", "響尾蛇", ["Arizona", "Diamondbacks", "D-backs"], "29"),
    CanonicalTeam("MLB_ATL", "baseball", "MLB", "ATL", "Atlanta Braves", "亞特蘭大勇士", "勇士", ["Atlanta", "Braves"], "15"),
    CanonicalTeam("MLB_BAL", "baseball", "MLB", "BAL", "Baltimore Orioles", "巴爾的摩金鶯", "金鶯", ["Baltimore", "Orioles", "O's"], "17"),
    CanonicalTeam("MLB_BOS", "baseball", "MLB", "BOS", "Boston Red Sox", "波士頓紅襪", "紅襪", ["Boston", "Red Sox"], "2"),
    CanonicalTeam("MLB_CHC", "baseball", "MLB", "CHC", "Chicago Cubs", "芝加哥小熊", "小熊", ["Chicago Cubs", "Cubs"], "6"),
    CanonicalTeam("MLB_CWS", "baseball", "MLB", "CWS", "Chicago White Sox", "芝加哥白襪", "白襪", ["White Sox", "CHW"], "4"),
    CanonicalTeam("MLB_CIN", "baseball", "MLB", "CIN", "Cincinnati Reds", "辛辛那提紅人", "紅人", ["Cincinnati", "Reds"], "7"),
    CanonicalTeam("MLB_CLE", "baseball", "MLB", "CLE", "Cleveland Guardians", "克里夫蘭守護者", "守護者", ["Cleveland", "Guardians", "印地安人", "Indians"], "5"),
    CanonicalTeam("MLB_COL", "baseball", "MLB", "COL", "Colorado Rockies", "科羅拉多落磯", "落磯", ["Colorado", "Rockies"], "27"),
    CanonicalTeam("MLB_DET", "baseball", "MLB", "DET", "Detroit Tigers", "底特律老虎", "老虎", ["Detroit", "Tigers"], "12"),
    CanonicalTeam("MLB_HOU", "baseball", "MLB", "HOU", "Houston Astros", "休士頓太空人", "太空人", ["Houston", "Astros"], "18"),
    CanonicalTeam("MLB_KC", "baseball", "MLB", "KC", "Kansas City Royals", "堪薩斯皇家", "皇家", ["Kansas City", "Royals", "KCR"], "25"),
    CanonicalTeam("MLB_LAA", "baseball", "MLB", "LAA", "Los Angeles Angels", "洛杉磯天使", "天使", ["LA Angels", "Angels", "Halos"], "3"),
    CanonicalTeam("MLB_LAD", "baseball", "MLB", "LAD", "Los Angeles Dodgers", "洛杉磯道奇", "道奇", ["LA Dodgers", "Dodgers"], "19"),
    CanonicalTeam("MLB_MIA", "baseball", "MLB", "MIA", "Miami Marlins", "邁阿密馬林魚", "馬林魚", ["Miami", "Marlins"], "28"),
    CanonicalTeam("MLB_MIL", "baseball", "MLB", "MIL", "Milwaukee Brewers", "密爾瓦基釀酒人", "釀酒人", ["Milwaukee", "Brewers"], "8"),
    CanonicalTeam("MLB_MIN", "baseball", "MLB", "MIN", "Minnesota Twins", "明尼蘇達雙城", "雙城", ["Minnesota", "Twins"], "14"),
    CanonicalTeam("MLB_NYM", "baseball", "MLB", "NYM", "New York Mets", "紐約大都會", "大都會", ["Mets", "NY Mets"], "21"),
    CanonicalTeam("MLB_NYY", "baseball", "MLB", "NYY", "New York Yankees", "紐約洋基", "洋基", ["Yankees", "NY Yankees"], "1"),
    CanonicalTeam("MLB_OAK", "baseball", "MLB", "OAK", "Athletics", "運動家", "運動家", ["Oakland Athletics", "Oakland", "A's", "奧克蘭運動家"], "11"),
    CanonicalTeam("MLB_PHI", "baseball", "MLB", "PHI", "Philadelphia Phillies", "費城費城人", "費城人", ["Philadelphia", "Phillies"], "22"),
    CanonicalTeam("MLB_PIT", "baseball", "MLB", "PIT", "Pittsburgh Pirates", "匹茲堡海盜", "海盜", ["Pittsburgh", "Pirates"], "9"),
    CanonicalTeam("MLB_SD", "baseball", "MLB", "SD", "San Diego Padres", "聖地牙哥教士", "教士", ["San Diego", "Padres", "SDP"], "26"),
    CanonicalTeam("MLB_SF", "baseball", "MLB", "SF", "San Francisco Giants", "舊金山巨人", "巨人", ["San Francisco", "Giants", "SFG"], "20"),
    CanonicalTeam("MLB_SEA", "baseball", "MLB", "SEA", "Seattle Mariners", "西雅圖水手", "水手", ["Seattle", "Mariners"], "13"),
    CanonicalTeam("MLB_STL", "baseball", "MLB", "STL", "St. Louis Cardinals", "聖路易紅雀", "紅雀", ["St. Louis", "Cardinals"], "10"),
    CanonicalTeam("MLB_TB", "baseball", "MLB", "TB", "Tampa Bay Rays", "坦帕灣光芒", "光芒", ["Tampa Bay", "Rays", "TBR"], "30"),
    CanonicalTeam("MLB_TEX", "baseball", "MLB", "TEX", "Texas Rangers", "德州遊騎兵", "遊騎兵", ["Texas", "Rangers"], "23"),
    CanonicalTeam("MLB_TOR", "baseball", "MLB", "TOR", "Toronto Blue Jays", "多倫多藍鳥", "藍鳥", ["Toronto", "Blue Jays", "Jays"], "24"),
    CanonicalTeam("MLB_WSH", "baseball", "MLB", "WSH", "Washington Nationals", "華盛頓國民", "國民", ["Washington", "Nationals", "Nats", "WAS"], "16"),
]

# =========================================================================
# Soccer Registry (Major European Teams)
# =========================================================================
SOCCER_TEAMS: List[CanonicalTeam] = [
    CanonicalTeam("SOC_ARS", "soccer", "PREMIER", "ARS", "Arsenal", "兵工廠", "兵工廠", ["阿森納", "槍手", "Arsenal FC"]),
    CanonicalTeam("SOC_MCI", "soccer", "PREMIER", "MCI", "Manchester City", "曼城", "曼城", ["曼徹斯特城", "Man City"]),
    CanonicalTeam("SOC_LIV", "soccer", "PREMIER", "LIV", "Liverpool", "利物浦", "利物浦", ["紅軍", "Liverpool FC"]),
    CanonicalTeam("SOC_CHE", "soccer", "PREMIER", "CHE", "Chelsea", "切爾西", "切爾西", ["車路士", "藍軍", "Chelsea FC"]),
    CanonicalTeam("SOC_MUN", "soccer", "PREMIER", "MUN", "Manchester United", "曼聯", "曼聯", ["曼徹斯特聯", "紅魔", "Man United"]),
    CanonicalTeam("SOC_TOT", "soccer", "PREMIER", "TOT", "Tottenham Hotspur", "托特納姆熱刺", "熱刺", ["熱刺隊", "Spurs"]),
    CanonicalTeam("SOC_NEW", "soccer", "PREMIER", "NEW", "Newcastle United", "紐卡索聯", "紐卡索", ["紐卡素", "喜鵲"]),
    CanonicalTeam("SOC_AVL", "soccer", "PREMIER", "AVL", "Aston Villa", "阿斯頓維拉", "阿斯頓維拉", ["阿士東維拉", "維拉"]),
    CanonicalTeam("SOC_BHA", "soccer", "PREMIER", "BHA", "Brighton & Hove Albion", "布萊頓", "布萊頓", ["白禮頓"]),
    CanonicalTeam("SOC_WHU", "soccer", "PREMIER", "WHU", "West Ham United", "西漢姆聯", "西漢姆", ["韋斯咸", "鐵鎚"]),
    CanonicalTeam("SOC_FUL", "soccer", "PREMIER", "FUL", "Fulham", "富勒姆", "富勒姆", ["富咸"]),
    CanonicalTeam("SOC_WOL", "soccer", "PREMIER", "WOL", "Wolverhampton Wanderers", "狼隊", "狼隊", ["伍爾弗漢普頓"]),
    CanonicalTeam("SOC_EVE", "soccer", "PREMIER", "EVE", "Everton", "艾佛頓", "艾佛頓", ["愛華頓", "太妃糖"]),
    CanonicalTeam("SOC_BRE", "soccer", "PREMIER", "BRE", "Brentford", "布倫特福德", "布倫特福德", ["賓福特"]),
    CanonicalTeam("SOC_CRY", "soccer", "PREMIER", "CRY", "Crystal Palace", "水晶宮", "水晶宮", ["水晶宮隊"]),
    CanonicalTeam("SOC_BOU", "soccer", "PREMIER", "BOU", "Bournemouth", "伯恩茅斯", "伯恩茅斯", ["般尼茅夫"]),
    CanonicalTeam("SOC_NFO", "soccer", "PREMIER", "NFO", "Nottingham Forest", "諾丁漢森林", "諾丁漢森林", ["諾定咸森林"]),
    CanonicalTeam("SOC_RMA", "soccer", "CHAMPIONS", "RMA", "Real Madrid", "皇家馬德里", "皇馬", ["Real Madrid CF", "銀河艦隊"]),
    CanonicalTeam("SOC_BAR", "soccer", "CHAMPIONS", "BAR", "Barcelona", "巴塞隆納", "巴薩", ["FC Barcelona"]),
    CanonicalTeam("SOC_BAY", "soccer", "CHAMPIONS", "BAY", "Bayern Munich", "拜仁慕尼黑", "拜仁", ["FC Bayern"]),
    CanonicalTeam("SOC_PSG", "soccer", "CHAMPIONS", "PSG", "Paris Saint-Germain", "巴黎聖日耳曼", "大巴黎", ["PSG"]),
    CanonicalTeam("SOC_INT", "soccer", "CHAMPIONS", "INT", "Inter Milan", "國際米蘭", "國米", ["Inter"]),
    CanonicalTeam("SOC_JUV", "soccer", "CHAMPIONS", "JUV", "Juventus", "尤文圖斯", "尤文", ["Juventus FC", "斑馬軍團"]),
]

# LaLiga clubs observed in the configured Football-Data esp.1 seasons. The
# aliases intentionally include that dataset's short labels and ESPN names.
# Real Madrid and Barcelona already have shared soccer identities above and
# are retained rather than duplicated here.
LALIGA_TEAMS: List[CanonicalTeam] = [
    CanonicalTeam("SOC_ESP_ALA", "soccer", "LALIGA", "ALA", "Deportivo Alaves", "阿拉維斯", "阿拉維斯", ["Alaves", "Deportivo Alavés", "Deportivo Alaves"]),
    CanonicalTeam("SOC_ESP_ALM", "soccer", "LALIGA", "ALM", "Almeria", "阿爾梅里亞", "阿爾梅里亞", ["Almería", "UD Almeria", "UD Almería"]),
    CanonicalTeam("SOC_ESP_RAY", "soccer", "LALIGA", "RAY", "Rayo Vallecano", "巴列卡諾", "巴列卡諾", ["Vallecano"]),
    CanonicalTeam("SOC_ESP_ATH", "soccer", "LALIGA", "ATH", "Athletic Club", "畢爾包競技", "畢爾包", ["Ath Bilbao", "Athletic Bilbao", "Athletic Club Bilbao"]),
    CanonicalTeam("SOC_ESP_ATM", "soccer", "LALIGA", "ATM", "Atletico Madrid", "馬德里競技", "馬德里競技", ["Ath Madrid", "Atlético Madrid", "Atletico de Madrid", "Atlético de Madrid"]),
    CanonicalTeam("SOC_ESP_BET", "soccer", "LALIGA", "BET", "Real Betis", "皇家貝蒂斯", "貝蒂斯", ["Betis"]),
    CanonicalTeam("SOC_ESP_CAD", "soccer", "LALIGA", "CAD", "Cadiz", "加的斯", "加的斯", ["Cádiz", "Cadiz CF"]),
    CanonicalTeam("SOC_ESP_CEL", "soccer", "LALIGA", "CEL", "Celta Vigo", "維戈塞爾塔", "塞爾塔", ["Celta", "Celta de Vigo", "RC Celta"]),
    CanonicalTeam("SOC_ESP_ELC", "soccer", "LALIGA", "ELC", "Elche", "埃爾切", "埃爾切", ["Elche CF"]),
    CanonicalTeam("SOC_ESP_ESP", "soccer", "LALIGA", "ESP", "Espanyol", "西班牙人", "西班牙人", ["Espanol", "RCD Espanyol", "Espanyol Barcelona"]),
    CanonicalTeam("SOC_ESP_GET", "soccer", "LALIGA", "GET", "Getafe", "赫塔費", "赫塔費", ["Getafe CF"]),
    CanonicalTeam("SOC_ESP_GIR", "soccer", "LALIGA", "GIR", "Girona", "吉羅納", "吉羅納", ["Girona FC"]),
    CanonicalTeam("SOC_ESP_GRA", "soccer", "LALIGA", "GRA", "Granada", "格拉納達", "格拉納達", ["Granada CF"]),
    CanonicalTeam("SOC_ESP_LAC", "soccer", "LALIGA", "LAC", "Deportivo La Coruna", "拉科魯尼亞", "拉科魯尼亞", ["Deportivo", "La Coruna", "Deportivo La Coruña", "Deportivo La Coruna"]),
    CanonicalTeam("SOC_ESP_LPA", "soccer", "LALIGA", "LPA", "Las Palmas", "拉斯帕爾馬斯", "拉斯帕爾馬斯", ["UD Las Palmas"]),
    CanonicalTeam("SOC_ESP_LEG", "soccer", "LALIGA", "LEG", "Leganes", "萊加內斯", "萊加內斯", ["Leganés", "CD Leganes", "CD Leganés"]),
    CanonicalTeam("SOC_ESP_LEV", "soccer", "LALIGA", "LEV", "Levante", "萊萬特", "萊萬特", ["Levante UD"]),
    CanonicalTeam("SOC_ESP_MAL", "soccer", "LALIGA", "MAL", "Malaga", "馬拉加", "馬拉加", ["Málaga", "Malaga CF", "Málaga CF"]),
    CanonicalTeam("SOC_ESP_MLL", "soccer", "LALIGA", "MLL", "Mallorca", "馬略卡", "馬略卡", ["RCD Mallorca"]),
    CanonicalTeam("SOC_ESP_OSA", "soccer", "LALIGA", "OSA", "Osasuna", "奧薩蘇納", "奧薩蘇納", ["CA Osasuna"]),
    CanonicalTeam("SOC_ESP_OVI", "soccer", "LALIGA", "OVI", "Real Oviedo", "皇家奧維耶多", "奧維耶多", ["Oviedo"]),
    CanonicalTeam("SOC_ESP_RSC", "soccer", "LALIGA", "RSC", "Racing Santander", "桑坦德競技", "桑坦德", ["Santander", "Racing de Santander"]),
    CanonicalTeam("SOC_ESP_SEV", "soccer", "LALIGA", "SEV", "Sevilla", "塞維亞", "塞維亞", ["Sevilla FC"]),
    CanonicalTeam("SOC_ESP_SOC", "soccer", "LALIGA", "RSO", "Real Sociedad", "皇家社會", "皇家社會", ["Sociedad"]),
    CanonicalTeam("SOC_ESP_VAL", "soccer", "LALIGA", "VAL", "Valencia", "瓦倫西亞", "瓦倫西亞", ["Valencia CF"]),
    CanonicalTeam("SOC_ESP_VLD", "soccer", "LALIGA", "VLD", "Real Valladolid", "皇家巴利亞多利德", "巴利亞多利德", ["Valladolid"]),
    CanonicalTeam("SOC_ESP_VIL", "soccer", "LALIGA", "VIL", "Villarreal", "比利亞雷亞爾", "比利亞雷亞爾", ["Villarreal CF", "比亞雷亞爾"]),
]

# These exact Chinese names were observed in the Playsport snapshots; English
# names and provider IDs are taken from the accompanying ESPN team snapshots.
# Only teams needed to match the current source ledger are registered here.
COLOMBIA_PRIMERA_A_TEAMS: List[CanonicalTeam] = [
    CanonicalTeam("SOC_COL_AGD", "soccer", "COLOMBIA_PRIMERA_A", "AGD", "Águilas Doradas", "里奧內格羅金鷹", "里奧內格羅金鷹", ["Aguilas Doradas", "Rionegro Águilas"]),
    CanonicalTeam("SOC_COL_BUC", "soccer", "COLOMBIA_PRIMERA_A", "BUC", "Atlético Bucaramanga", "布卡拉曼加競技", "布卡拉曼加競技", ["Bucaramanga"]),
    CanonicalTeam("SOC_COL_CAL", "soccer", "COLOMBIA_PRIMERA_A", "CAL", "Once Caldas", "卡爾達斯", "卡爾達斯", ["Once Caldas DAF"]),
    CanonicalTeam("SOC_COL_MIL", "soccer", "COLOMBIA_PRIMERA_A", "MIL", "Millonarios", "百萬富翁", "百萬富翁", ["Millonarios FC"]),
    # Exact Playsport names were cross-checked against the saved ESPN col.1
    # scoreboard event 401878008 at 2026-10-14T21:30Z (feed SHA is recorded in
    # artifacts/improvements_20261014/football_sources/manifest.json).
    CanonicalTeam("SOC_COL_PER", "soccer", "COLOMBIA_PRIMERA_A", "PER", "Deportivo Pereira", "佩雷拉體育", "佩雷拉體育", ["ESPN_TEAM_5486"]),
    CanonicalTeam("SOC_COL_JUN", "soccer", "COLOMBIA_PRIMERA_A", "JUN", "Atlético Junior", "青年體育會", "青年體育會", ["ESPN_TEAM_4815"]),
]

COSTA_RICA_PRIMERA_TEAMS: List[CanonicalTeam] = [
    CanonicalTeam("SOC_CRC_PUN", "soccer", "COSTA_RICA_PRIMERA", "PUN", "Puntarenas FC", "普塔雷納斯", "普塔雷納斯", ["Puntarenas"]),
    CanonicalTeam("SOC_CRC_CAR", "soccer", "COSTA_RICA_PRIMERA", "CAR", "Cartaginés", "肯塔吉內斯", "肯塔吉內斯", ["Cartagines", "CS Cartaginés"]),
    CanonicalTeam("SOC_CRC_ADS", "soccer", "COSTA_RICA_PRIMERA", "ADSC", "AD San Carlos", "聖卡洛斯", "聖卡洛斯", ["Asociación Deportiva San Carlos"]),
    CanonicalTeam("SOC_CRC_INT", "soccer", "COSTA_RICA_PRIMERA", "ISC", "Inter de San Carlos", "國際聖卡洛斯", "國際聖卡洛斯", ["Inter San Carlos", "Inter de San Carlos"]),
    # Exact Chinese labels were paired by event start with the saved ESPN
    # crc.1 scoreboard rows 401876840 and 401876841. See the same manifest
    # for raw source hashes and observation times.
    CanonicalTeam("SOC_CRC_ESC", "soccer", "COSTA_RICA_PRIMERA", "ESC", "Escorpiones Belén", "貝倫蠍子", "貝倫蠍子", ["ESPN_TEAM_132447"]),
    CanonicalTeam("SOC_CRC_PZ", "soccer", "COSTA_RICA_PRIMERA", "PZ", "Pérez Zeledón", "佩雷斯塞萊東", "佩雷斯塞萊東", ["ESPN_TEAM_7234"]),
    CanonicalTeam("SOC_CRC_HER", "soccer", "COSTA_RICA_PRIMERA", "HER", "Herediano", "希雷迪亞諾", "希雷迪亞諾", ["ESPN_TEAM_862"]),
    CanonicalTeam("SOC_CRC_ALA", "soccer", "COSTA_RICA_PRIMERA", "ALA", "Alajuelense", "阿拉倫斯", "阿拉倫斯", ["ESPN_TEAM_2057"]),
]

# Exact 11-match Playsport slate observed on 2026-10-14/15 and paired to the
# ESPN afc.cup scoreboard by event date/time, away/home sides, English names,
# and ESPN team IDs. This list is only the observed slate, not full AFC
# Champions League Two roster coverage. Raw ESPN feed hashes are saved under
# artifacts/program_review_20261014/source_comparison_20261015/afc_cup/.
AFC_CHAMPIONS_LEAGUE_TWO_TEAMS: List[CanonicalTeam] = [
    CanonicalTeam("SOC_AFC2_GOL", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "GOL", "Gol Gohar FC Sirjan", "錫爾詹戈爾戈哈爾", "錫爾詹戈爾戈哈爾", ["ESPN_TEAM_132926"]),
    CanonicalTeam("SOC_AFC2_MUH", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "MUH", "Al Muharraq", "阿爾穆哈拉克", "阿爾穆哈拉克", ["ESPN_TEAM_21006"]),
    CanonicalTeam("SOC_AFC2_RAY", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "RAY", "Al Rayyan", "阿爾雷恩", "阿爾雷恩", ["ESPN_TEAM_7527"]),
    CanonicalTeam("SOC_AFC2_TAW", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "TAW", "Al Taawoun", "阿爾塔旺", "阿爾塔旺", ["ESPN_TEAM_18459"]),
    CanonicalTeam("SOC_AFC2_ARK", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "ARK", "Arkadag", "阿卡達", "阿卡達", ["ESPN_TEAM_131374"]),
    CanonicalTeam("SOC_AFC2_JAZ", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "JAZ", "Al-Jazira", "阿爾賈齊拉阿布達比", "阿爾賈齊拉阿布達比", ["ESPN_TEAM_8364"]),
    CanonicalTeam("SOC_AFC2_KHA", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "KHA", "Khaldiya", "阿爾哈爾迪亞", "阿爾哈爾迪亞", ["ESPN_TEAM_22354"]),
    CanonicalTeam("SOC_AFC2_KUW", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "KUW", "Kuwait SC", "科威特SC", "科威特SC", ["ESPN_TEAM_21008"]),
    CanonicalTeam("SOC_AFC2_NAH", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "NAH", "Al-Nahda Muscat Club", "阿爾納達", "阿爾納達", ["ESPN_TEAM_21994"]),
    CanonicalTeam("SOC_AFC2_FAI", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "FAI", "Al-Faisaly", "阿爾費薩里安曼", "阿爾費薩里安曼", ["ESPN_TEAM_21024"]),
    CanonicalTeam("SOC_AFC2_LCS", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "LCS", "Lion City Sailors FC", "獅城水手", "獅城水手", ["ESPN_TEAM_8040"]),
    CanonicalTeam("SOC_AFC2_TPO", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "TPO", "Tai Po FC", "大埔", "大埔", ["ESPN_TEAM_131377"]),
    CanonicalTeam("SOC_AFC2_PPC", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "PPC", "Phnom Penh Crown", "金邊皇冠俱樂部", "金邊皇冠俱樂部", ["ESPN_TEAM_21432"]),
    CanonicalTeam("SOC_AFC2_GAN", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "GAN", "Gangwon FC", "江原FC", "江原FC", ["ESPN_TEAM_131373"]),
    CanonicalTeam("SOC_AFC2_ADE", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "ADE", "Adelaide United", "阿德雷德聯", "阿德雷德聯", ["ESPN_TEAM_5321"]),
    CanonicalTeam("SOC_AFC2_PAT", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "PAT", "BG Pathum United", "BG巴吞聯", "BG巴吞聯", ["ESPN_TEAM_8519"]),
    CanonicalTeam("SOC_AFC2_MAC", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "MAC", "Machida Zelvia", "町田澤維亞", "町田澤維亞", ["ESPN_TEAM_22167"]),
    CanonicalTeam("SOC_AFC2_TAM", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "TAM", "BG Tampines Rovers FC", "淡濱尼流浪", "淡濱尼流浪", ["ESPN_TEAM_7998"]),
    CanonicalTeam("SOC_AFC2_KIT", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "KIT", "Kitchee", "傑志", "傑志", ["ESPN_TEAM_17686"]),
    CanonicalTeam("SOC_AFC2_KUC", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "KUC", "Kuching City", "古晉市", "古晉市", ["ESPN_TEAM_21844"]),
    CanonicalTeam("SOC_AFC2_SHS", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "SHS", "Shanghai Shenhua", "上海申花", "上海申花", ["ESPN_TEAM_977"]),
    CanonicalTeam("SOC_AFC2_SVR", "soccer", "AFC_CHAMPIONS_LEAGUE_TWO", "SVR", "Preah Khan Reach Svay Rieng FC", "PKR柴楨", "PKR柴楨", ["ESPN_TEAM_133293"]),
]

# Three Saudi Pro League matches observed on the Playsport board for Oct. 15,
# 2026. Chinese labels, ESPN names/IDs, and UTC home/away positions were
# cross-checked against the saved ksa.1 scoreboard and teams feeds referenced
# in artifacts/program_review_20261014/source_comparison_20261015/saudi_libertadores/manifest.json.
SAUDI_PRO_LEAGUE_TEAMS: List[CanonicalTeam] = [
    CanonicalTeam("SOC_KSA_KHO", "soccer", "SAUDI_PRO_LEAGUE", "KHO", "Al Kholood", "阿爾科盧德", "阿爾科盧德", ["ESPN_TEAM_22028"]),
    CanonicalTeam("SOC_KSA_FAI", "soccer", "SAUDI_PRO_LEAGUE", "FAI", "Al Faisaly", "阿爾費薩里哈馬赫", "阿爾費薩里哈馬赫", ["ESPN_TEAM_21446"]),
    CanonicalTeam("SOC_KSA_FAY", "soccer", "SAUDI_PRO_LEAGUE", "FAY", "Al Fayha", "阿爾費哈", "阿爾費哈", ["ESPN_TEAM_21827"]),
    CanonicalTeam("SOC_KSA_KHA", "soccer", "SAUDI_PRO_LEAGUE", "KHA", "Al Khaleej", "阿爾卡赫利", "阿爾卡赫利", ["ESPN_TEAM_21829"]),
    CanonicalTeam("SOC_KSA_FAT", "soccer", "SAUDI_PRO_LEAGUE", "FAT", "Al Fateh", "阿爾法特", "阿爾法特", ["ESPN_TEAM_13033"]),
    CanonicalTeam("SOC_KSA_HAZ", "soccer", "SAUDI_PRO_LEAGUE", "HAZ", "Al Hazem", "阿爾哈森姆", "阿爾哈森姆", ["ESPN_TEAM_21964"]),
]

# One Libertadores match was available in the captured Playsport slate. These
# are observed-slate aliases, not complete competition roster coverage.
CONMEBOL_LIBERTADORES_TEAMS: List[CanonicalTeam] = [
    CanonicalTeam("SOC_LIB_PAL", "soccer", "CONMEBOL_LIBERTADORES", "PAL", "Palmeiras", "帕梅拉斯", "帕梅拉斯", ["ESPN_TEAM_2029"]),
    CanonicalTeam("SOC_LIB_FLU", "soccer", "CONMEBOL_LIBERTADORES", "FLU", "Fluminense", "弗魯米內斯", "弗魯米內斯", ["ESPN_TEAM_3445"]),
]

# MLS teams appearing in the October 14, 2026 Playsport board. English names
# and ESPN IDs come from the saved usa.1 teams/scoreboard feeds; Chinese labels
# are the exact paired source names for these 15 event IDs. This set captures
# every MLS team in that observed 15-game slate, not a permanent full-roster
# guarantee. ESPN IDs are namespaced aliases, never Playsport team IDs.
MLS_TEAMS: List[CanonicalTeam] = [
    CanonicalTeam("MLS_ATL", "soccer", "MLS", "ATL", "Atlanta United FC", "亞特蘭大聯", "亞特蘭大聯", ["Atlanta United", "Atlanta", "ESPN_TEAM_18418"]),
    CanonicalTeam("MLS_ATX", "soccer", "MLS", "ATX", "Austin FC", "奧斯汀", "奧斯汀", ["Austin", "ESPN_TEAM_20906"]),
    CanonicalTeam("MLS_MTL", "soccer", "MLS", "MTL", "CF Montréal", "蒙特婁", "蒙特婁", ["Montreal", "CF Montreal", "ESPN_TEAM_9720"]),
    CanonicalTeam("MLS_CLT", "soccer", "MLS", "CLT", "Charlotte FC", "夏洛特", "夏洛特", ["Charlotte", "ESPN_TEAM_21300"]),
    CanonicalTeam("MLS_CHI", "soccer", "MLS", "CHI", "Chicago Fire FC", "芝加哥火焰", "芝加哥火焰", ["Chicago Fire", "ESPN_TEAM_182"]),
    CanonicalTeam("MLS_COL", "soccer", "MLS", "COL", "Colorado Rapids", "科羅拉多急流", "科羅拉多急流", ["Colorado", "ESPN_TEAM_184"]),
    CanonicalTeam("MLS_CLB", "soccer", "MLS", "CLB", "Columbus Crew", "哥倫布機員", "哥倫布機員", ["Columbus", "ESPN_TEAM_183"]),
    CanonicalTeam("MLS_DC", "soccer", "MLS", "DC", "D.C. United", "華盛頓特區聯", "華盛頓特區聯", ["DC United", "Washington DC", "ESPN_TEAM_193"]),
    CanonicalTeam("MLS_CIN", "soccer", "MLS", "CIN", "FC Cincinnati", "辛辛那提", "辛辛那提", ["Cincinnati", "ESPN_TEAM_18267"]),
    CanonicalTeam("MLS_DAL", "soccer", "MLS", "DAL", "FC Dallas", "達拉斯", "達拉斯", ["Dallas", "ESPN_TEAM_185"]),
    CanonicalTeam("MLS_HOU", "soccer", "MLS", "HOU", "Houston Dynamo FC", "休士頓發電機", "休士頓發電機", ["Houston Dynamo", "ESPN_TEAM_6077"]),
    CanonicalTeam("MLS_MIA", "soccer", "MLS", "MIA", "Inter Miami CF", "國際邁阿密", "國際邁阿密", ["Inter Miami", "ESPN_TEAM_20232"]),
    CanonicalTeam("MLS_LAG", "soccer", "MLS", "LA", "LA Galaxy", "洛杉磯銀河", "洛杉磯銀河", ["Los Angeles Galaxy", "Galaxy", "ESPN_TEAM_187"]),
    CanonicalTeam("MLS_LAFC", "soccer", "MLS", "LAFC", "LAFC", "洛杉磯FC", "洛杉磯FC", ["Los Angeles FC", "洛杉磯", "ESPN_TEAM_18966"]),
    CanonicalTeam("MLS_MIN", "soccer", "MLS", "MIN", "Minnesota United FC", "明尼蘇達聯", "明尼蘇達聯", ["Minnesota United", "ESPN_TEAM_17362"]),
    CanonicalTeam("MLS_NSH", "soccer", "MLS", "NSH", "Nashville SC", "納許維爾", "納許維爾", ["Nashville", "ESPN_TEAM_18986"]),
    CanonicalTeam("MLS_NE", "soccer", "MLS", "NE", "New England Revolution", "新英格蘭革命", "新英格蘭革命", ["New England", "ESPN_TEAM_189"]),
    CanonicalTeam("MLS_NYC", "soccer", "MLS", "NYC", "New York City FC", "紐約城", "紐約城", ["NYCFC", "ESPN_TEAM_17606"]),
    CanonicalTeam("MLS_ORL", "soccer", "MLS", "ORL", "Orlando City SC", "奧蘭多城", "奧蘭多城", ["Orlando City", "ESPN_TEAM_12011"]),
    CanonicalTeam("MLS_PHI", "soccer", "MLS", "PHI", "Philadelphia Union", "費城聯", "費城聯", ["Philadelphia", "ESPN_TEAM_10739"]),
    CanonicalTeam("MLS_POR", "soccer", "MLS", "POR", "Portland Timbers", "波特蘭伐木者", "波特蘭伐木者", ["Portland", "ESPN_TEAM_9723"]),
    CanonicalTeam("MLS_RSL", "soccer", "MLS", "RSL", "Real Salt Lake", "皇家鹽湖城", "皇家鹽湖城", ["Salt Lake", "ESPN_TEAM_4771"]),
    CanonicalTeam("MLS_RBNY", "soccer", "MLS", "RBNY", "Red Bull New York", "紐約紅牛", "紐約紅牛", ["New York Red Bulls", "New York Red Bull", "ESPN_TEAM_190"]),
    CanonicalTeam("MLS_SD", "soccer", "MLS", "SD", "San Diego FC", "聖地牙哥", "聖地牙哥", ["San Diego", "ESPN_TEAM_22529"]),
    CanonicalTeam("MLS_SJ", "soccer", "MLS", "SJ", "San Jose Earthquakes", "聖荷西地震", "聖荷西地震", ["San Jose", "ESPN_TEAM_191"]),
    CanonicalTeam("MLS_SEA", "soccer", "MLS", "SEA", "Seattle Sounders FC", "西雅圖海灣者", "西雅圖海灣者", ["Seattle Sounders", "Seattle", "ESPN_TEAM_9726"]),
    CanonicalTeam("MLS_SKC", "soccer", "MLS", "SKC", "Sporting Kansas City", "堪薩斯城體育", "堪薩斯城體育", ["Kansas City", "Sporting KC", "ESPN_TEAM_186"]),
    CanonicalTeam("MLS_STL", "soccer", "MLS", "STL", "St. Louis CITY SC", "聖路易城", "聖路易城", ["St Louis City", "St. Louis City", "ESPN_TEAM_21812"]),
    CanonicalTeam("MLS_TOR", "soccer", "MLS", "TOR", "Toronto FC", "多倫多", "多倫多", ["Toronto", "ESPN_TEAM_7318"]),
    CanonicalTeam("MLS_VAN", "soccer", "MLS", "VAN", "Vancouver Whitecaps", "溫哥華白浪", "溫哥華白浪", ["Vancouver", "ESPN_TEAM_9727"]),
]

# NBA identities observed in the Playsport source snapshots and the saved
# ESPN scoreboard sample. These are exact source labels for the four teams
# needed by that historical run; this is not a claim of complete NBA roster
# coverage. ESPN team IDs from that sample are documented here for provenance
# but are not treated as Playsport team IDs.
NBA_TEAMS: List[CanonicalTeam] = [
    CanonicalTeam("NBA_GSW", "basketball", "NBA", "GSW", "Golden State Warriors", "金州勇士", "勇士", ["Warriors", "Golden State", "金州戰士"]),
    CanonicalTeam("NBA_LAL", "basketball", "NBA", "LAL", "Los Angeles Lakers", "洛杉磯湖人", "湖人", ["Lakers", "LA Lakers", "洛杉磯湖人隊"]),
    CanonicalTeam("NBA_POR", "basketball", "NBA", "POR", "Portland Trail Blazers", "波特蘭拓荒者", "拓荒者", ["Trail Blazers", "Portland", "Blazers", "波特蘭開拓者"]),
    CanonicalTeam("NBA_SAC", "basketball", "NBA", "SAC", "Sacramento Kings", "沙加緬度國王", "國王", ["Kings", "Sacramento", "沙加緬度國王隊"]),
    # The exact Chinese source labels and English ESPN names were paired by
    # home/away side and UTC start time with the saved Oct. 14 scoreboard.
    # ESPN team IDs and raw feed hashes are in
    # artifacts/program_review_20261014/source_comparison_20261015/manifest.json.
    CanonicalTeam("NBA_BKN", "basketball", "NBA", "BKN", "Brooklyn Nets", "布魯克林籃網", "籃網", ["ESPN_TEAM_17"]),
    CanonicalTeam("NBA_MIA", "basketball", "NBA", "MIA", "Miami Heat", "邁阿密熱火", "熱火", ["ESPN_TEAM_14"]),
    CanonicalTeam("NBA_CHA", "basketball", "NBA", "CHA", "Charlotte Hornets", "夏洛特黃蜂", "黃蜂", ["ESPN_TEAM_30"]),
    CanonicalTeam("NBA_BOS", "basketball", "NBA", "BOS", "Boston Celtics", "波士頓塞爾提克", "塞爾提", ["ESPN_TEAM_2"]),
    CanonicalTeam("NBA_CHI", "basketball", "NBA", "CHI", "Chicago Bulls", "芝加哥公牛", "公牛", ["ESPN_TEAM_4"]),
    CanonicalTeam("NBA_MIL", "basketball", "NBA", "MIL", "Milwaukee Bucks", "密爾瓦基公鹿", "公鹿", ["ESPN_TEAM_15"]),
    CanonicalTeam("NBA_PHX", "basketball", "NBA", "PHX", "Phoenix Suns", "鳳凰城太陽", "太陽", ["ESPN_TEAM_21"]),
    CanonicalTeam("NBA_SAS", "basketball", "NBA", "SAS", "San Antonio Spurs", "聖安東尼奧馬刺", "馬刺", ["ESPN_TEAM_24"]),
    CanonicalTeam("NBA_DET", "basketball", "NBA", "DET", "Detroit Pistons", "底特律活塞", "活塞", ["ESPN_TEAM_8"]),
    CanonicalTeam("NBA_MIN", "basketball", "NBA", "MIN", "Minnesota Timberwolves", "明尼蘇達灰狼", "灰狼", ["ESPN_TEAM_16"]),
    CanonicalTeam("NBA_NO", "basketball", "NBA", "NO", "New Orleans Pelicans", "紐奧良鵜鶘", "鵜鶘", ["ESPN_TEAM_3"]),
    CanonicalTeam("NBA_DAL", "basketball", "NBA", "DAL", "Dallas Mavericks", "達拉斯獨行俠", "獨行俠", ["ESPN_TEAM_6"]),
    CanonicalTeam("NBA_DEN", "basketball", "NBA", "DEN", "Denver Nuggets", "丹佛金塊", "金塊", ["ESPN_TEAM_7"]),
    CanonicalTeam("NBA_LAC", "basketball", "NBA", "LAC", "LA Clippers", "洛杉磯快艇", "快艇", ["ESPN_TEAM_12"]),
]

# =========================================================================
# NFL Registry (Major Teams)
# =========================================================================
NFL_TEAMS: List[CanonicalTeam] = [
    CanonicalTeam("NFL_KC", "football", "NFL", "KC", "Kansas City Chiefs", "堪薩斯城酋長", "酋長", ["Kansas City", "Chiefs"]),
    CanonicalTeam("NFL_SF", "football", "NFL", "SF", "San Francisco 49ers", "舊金山四九人", "49人", ["San Francisco", "49ers"]),
    CanonicalTeam("NFL_BAL", "football", "NFL", "BAL", "Baltimore Ravens", "巴爾的摩烏鴉", "烏鴉", ["Baltimore", "Ravens"]),
    CanonicalTeam("NFL_BUF", "football", "NFL", "BUF", "Buffalo Bills", "水牛城比爾", "比爾", ["Buffalo", "Bills"]),
    CanonicalTeam("NFL_DET", "football", "NFL", "DET", "Detroit Lions", "底特律雄獅", "雄獅", ["Detroit", "Lions"]),
    CanonicalTeam("NFL_PHI", "football", "NFL", "PHI", "Philadelphia Eagles", "費城老鷹", "老鷹", ["Philadelphia", "Eagles"]),
    CanonicalTeam("NFL_DAL", "football", "NFL", "DAL", "Dallas Cowboys", "達拉斯牛仔", "牛仔", ["Dallas", "Cowboys"]),
    CanonicalTeam("NFL_GB", "football", "NFL", "GB", "Green Bay Packers", "綠灣包裝工", "包裝工", ["Green Bay", "Packers"]),
    CanonicalTeam("NFL_MIA", "football", "NFL", "MIA", "Miami Dolphins", "邁阿密海豚", "海豚", ["Miami", "Dolphins"]),
    CanonicalTeam("NFL_HOU", "football", "NFL", "HOU", "Houston Texans", "休士頓德州人", "德州人", ["Houston", "Texans"]),
    CanonicalTeam("NFL_CIN", "football", "NFL", "CIN", "Cincinnati Bengals", "辛辛那提孟加拉虎", "孟加拉虎", ["Cincinnati", "Bengals"]),
    CanonicalTeam("NFL_NYJ", "football", "NFL", "NYJ", "New York Jets", "紐約噴射機", "噴射機", ["New York Jets", "Jets"]),
]

# =========================================================================
# CPBL Registry (Taiwan Professional Baseball)
# =========================================================================
CPBL_TEAMS: List[CanonicalTeam] = [
    CanonicalTeam("CPBL_CTB", "baseball", "CPBL", "CTB", "CTBC Brothers", "中信兄弟", "兄弟", ["中信兄弟", "黃衫軍", "Brothers"]),
    CanonicalTeam("CPBL_UL", "baseball", "CPBL", "UL", "Uni-President 7-Eleven Lions", "統一7-ELEVEn獅", "統一獅", ["統一", "統一獅", "Lions"]),
    CanonicalTeam("CPBL_RM", "baseball", "CPBL", "RM", "Rakuten Monkeys", "樂天桃猿", "樂天", ["樂天桃猿", "桃猿", "Monkeys"]),
    CanonicalTeam("CPBL_WD", "baseball", "CPBL", "WD", "Wei Chuan Dragons", "味全龍", "味全", ["味全龍", "Dragons"]),
    CanonicalTeam("CPBL_FG", "baseball", "CPBL", "FG", "Fubon Guardians", "富邦悍將", "富邦", ["富邦悍將", "悍將", "Guardians"]),
    CanonicalTeam("CPBL_TSG", "baseball", "CPBL", "TSG", "TSG Hawks", "台鋼雄鷹", "台鋼", ["台鋼雄鷹", "雄鷹", "Hawks"]),
]


class TeamRegistry:
    """Registry maintaining canonical team entities and multi-lingual alias resolution."""

    def __init__(self, teams: Optional[List[CanonicalTeam]] = None):
        self._teams: Dict[str, CanonicalTeam] = {}
        # Keep the first record for legacy exact lookups and preserve every
        # collision separately so sport/league-scoped lookups can disambiguate
        # common short names such as the NBA and MLB "勇士".
        self._lookup: Dict[str, CanonicalTeam] = {}
        self._lookup_candidates: Dict[str, List[CanonicalTeam]] = {}
        initial_teams = teams or (MLB_TEAMS + SOCCER_TEAMS + LALIGA_TEAMS + COLOMBIA_PRIMERA_A_TEAMS
                                  + COSTA_RICA_PRIMERA_TEAMS + AFC_CHAMPIONS_LEAGUE_TWO_TEAMS
                                  + SAUDI_PRO_LEAGUE_TEAMS + CONMEBOL_LIBERTADORES_TEAMS
                                  + MLS_TEAMS + NBA_TEAMS + NFL_TEAMS + CPBL_TEAMS)
        for t in initial_teams:
            self.register_team(t)

    def register_team(self, team: CanonicalTeam) -> None:
        self._teams[team.canonical_id] = team
        # Register keys in lower-case for case-insensitive matching
        keys_to_index = [
            team.canonical_id,
            team.abbreviation,
            team.display_name_en,
            team.display_name_zh,
            team.short_name_zh,
        ]
        if team.playsport_team_id:
            keys_to_index.append(f"PS_TEAM_{team.playsport_team_id}")
            keys_to_index.append(f"{team.league}_{team.playsport_team_id}")

        for alias in team.aliases:
            keys_to_index.append(alias)

        for k in keys_to_index:
            cleaned = k.strip().lower()
            if cleaned:
                self._lookup.setdefault(cleaned, team)
                candidates = self._lookup_candidates.setdefault(cleaned, [])
                if all(existing.canonical_id != team.canonical_id for existing in candidates):
                    candidates.append(team)

    def resolve(
        self,
        name_or_alias: str,
        sport: Optional[str] = None,
        league: Optional[str] = None,
        playsport_team_id: Optional[str] = None,
    ) -> Optional[CanonicalTeam]:
        """Resolve any team alias, abbreviation, or ID into a CanonicalTeam."""
        if not name_or_alias and not playsport_team_id:
            return None

        # Soccer clubs participate in multiple competitions. League identifies
        # the event competition, not a separate identity for the same club.
        league_scope = None if sport == "soccer" else league

        # 1. Direct match by playsport_team_id if given
        if playsport_team_id and league:
            key = f"{league}_{playsport_team_id}".lower()
            candidates = self._matching_candidates(key, sport=sport, league=league_scope)
            if len(candidates) == 1:
                return candidates[0]

        cleaned = name_or_alias.strip().lower()

        # 2. Exact match in lookup
        if cleaned in self._lookup_candidates:
            candidates = self._matching_candidates(cleaned, sport=sport, league=league_scope)
            if len(candidates) == 1:
                return candidates[0]
            # A known exact name outside the requested scope must not fall
            # through to an approximate token from a different competition.
            return None

        # 3. Substring / Token matching
        token_matches: Dict[str, tuple[int, CanonicalTeam]] = {}
        for candidate_key, candidates in self._lookup_candidates.items():
            if len(candidate_key) < 2 or (candidate_key not in cleaned and cleaned not in candidate_key):
                continue
            for team in candidates:
                if sport and team.sport != sport:
                    continue
                if league_scope and team.league != league_scope:
                    continue
                previous = token_matches.get(team.canonical_id)
                if previous is None or len(candidate_key) > previous[0]:
                    token_matches[team.canonical_id] = (len(candidate_key), team)
        if token_matches:
            longest = max(length for length, _team in token_matches.values())
            best = {canonical_id: team for canonical_id, (length, team) in token_matches.items()
                    if length == longest}
            if len(best) == 1:
                return next(iter(best.values()))

        return None

    def _matching_candidates(self, key: str, *, sport: Optional[str], league: Optional[str]) -> List[CanonicalTeam]:
        candidates = self._lookup_candidates.get(key, [])
        return [team for team in candidates
                if (not sport or team.sport == sport)
                and (not league or team.league == league)]


# Global singleton registry
GLOBAL_TEAM_REGISTRY = TeamRegistry()
