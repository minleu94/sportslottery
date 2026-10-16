import requests, json, time

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

print('--- Test 1: ESPN Scoreboard API (MLB) ---')
try:
    r = requests.get('http://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard', headers=headers, timeout=8)
    data = r.json()
    events = data.get('events', [])
    print(f'ESPN MLB Status: {r.status_code}, Events Count: {len(events)}')
    if events:
        print(f'First event: {events[0].get("name")}, Date: {events[0].get("date")}')
except Exception as e:
    print('ESPN Error:', e)

print('\n--- Test 2: Playsport Scale MLB (Alliance 1) ---')
try:
    r = requests.get('https://www.playsport.cc/predict/scale?allianceid=1', headers=headers, timeout=8)
    print(f'Playsport Alliance 1 Status: {r.status_code}, HTML bytes: {len(r.text)}')
except Exception as e:
    print('Playsport Error:', e)

print('\n--- Test 3: Playsport Billboard (Alliance 1) ---')
try:
    r = requests.get('https://www.playsport.cc/billboard/mainPrediction?allianceid=1', headers=headers, timeout=8)
    print(f'Playsport Billboard Status: {r.status_code}, HTML bytes: {len(r.text)}')
except Exception as e:
    print('Playsport Billboard Error:', e)
