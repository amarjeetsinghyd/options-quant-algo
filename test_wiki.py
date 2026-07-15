import requests
from bs4 import BeautifulSoup

def get_nifty50_wiki():
    url = "https://en.wikipedia.org/wiki/NIFTY_50"
    html = requests.get(url).text
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', {'id': 'constituents'})
    symbols = []
    for row in table.find_all('tr')[1:]:
        cols = row.find_all('td')
        if len(cols) > 1:
            sym = cols[1].text.strip()
            symbols.append(sym)
    return symbols

def get_sensex30_wiki():
    url = "https://en.wikipedia.org/wiki/BSE_SENSEX"
    html = requests.get(url).text
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', {'id': 'constituents'})
    if not table:
        table = soup.find('table', {'class': 'wikitable'})
    symbols = []
    for row in table.find_all('tr')[1:]:
        cols = row.find_all('td')
        if len(cols) > 1:
            # Sensex wiki table has Ticker symbol in the second column usually
            sym = cols[1].text.strip()
            if 'BOM:' in sym:
                sym = sym.replace('BOM:', '').strip()
            symbols.append(sym)
    return symbols

print("Nifty 50:", get_nifty50_wiki())
print("Sensex 30:", get_sensex30_wiki())
