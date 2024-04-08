from selenium import webdriver
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import os

opts = webdriver.FirefoxOptions()
opts.add_argument("--headless")

driver = webdriver.Firefox(options=opts)
driver.get('https://www.csindex.com.cn/#/indices/family/list')

export_button = driver.find_elements(By.CLASS_NAME, 'ivu-btn ivu-btn-primary')

print(export_button.text)