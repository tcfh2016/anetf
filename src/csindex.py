import requests
from bs4 import BeautifulSoup

target_url = 'https://www.csindex.com.cn/#/indices/family/list'

def scrap_page(url):
    response = requests.get(url, verify=False)

    if response.status_code != 200:
        return f'status failed with {response.status_code}'
    else:
        soup = BeautifulSoup(response.text, 'html.parser')
        print(soup)

scrap_page(target_url)