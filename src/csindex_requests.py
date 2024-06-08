
import os
import time
import requests
import json
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

#ua = UserAgent()
#header = {'User-Agent':ua.random}

cookie = "token=code_space;"
header = {
    "cookie": cookie,
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "application/json;charset=UTF-8",
    "Connection": "keep-alive",
    #"Cookie": "_uab_collina=168940681022976356866423; zg_did=%7B%22did%22%3A%20%22189587e022939-0b53eb57924ecb8-412a2c3d-13c680-189587e022b249%22%7D; zg_6df0ba28cbd846a799ab8f527e8cc62b=%7B%22sid%22%3A%201692430519311%2C%22updated%22%3A%201692430554192%2C%22info%22%3A%201689406800439%2C%22superProperty%22%3A%20%22%7B%5C%22%E5%BA%94%E7%94%A8%E5%90%8D%E7%A7%B0%5C%22%3A%20%5C%22%E4%B8%AD%E8%AF%81%E6%8C%87%E6%95%B0%E5%AE%98%E7%BD%91%5C%22%7D%22%2C%22platform%22%3A%20%22%7B%7D%22%2C%22utm%22%3A%20%22%7B%7D%22%2C%22referrerDomain%22%3A%20%22cn.bing.com%22%2C%22landHref%22%3A%20%22https%3A%2F%2Fwww.csindex.com.cn%2F%22%2C%22prePath%22%3A%20%22https%3A%2F%2Fwww.csindex.com.cn%2F%23%2F%22%2C%22duration%22%3A%2021784.539999991655%2C%22zs%22%3A%200%2C%22sc%22%3A%200%2C%22firstScreen%22%3A%201692430519311%7D; ssxmod_itna=Yq+xcD9D0iitY7KGHD8Yb4BKRDhAYDBADxroxhnYOD052oGzDAxn40iDtoaT=3cYq4q3Rn+Be7WWnfh4I3O+Yw2xUWYOGeD=xYQDwxYoDUxGtDpxG6jbYwt=DWDYPGWDD4DmDim1D5xiUUDDUODY6XD7tMF+oyWutR/4DHihoY0R2njuLXjqGvD73MDDdMYixoNi4jChDYYYmKF3pTKDei+04jKYeL3x+QGYeQfG7PDDfTXGGdAiD===; Hm_lvt_f0fbc9a7e7e7f29a55a0c13718e9e542=1712582259,1712664681; tfstk=fzQiHUXoIpM7edPbOwY_-qIQStZ-AfTXgt3vHEp4YpJIBA3OgKvVB9QAXqC2ntXppNKv7RX3o9XP6NF6B9mcH9f9kcLairfVatxb1Kp2ntCVXG48y116lEP8ezU839_L2ODw0IP28IANC-xBh116lXw8ezUR1mxJGXVDutlETQpEuKJV3HueGpuwgVRqLWAXLK82bCkELCOq0fJwbdm-TdBVCwPSfxXfnp0PTCxMnZpIrL7IyH9PlpyPfPdwjcCwKquVRMTtWFpu-vJdg_s2xZmLVK_hTNSVOA2DS6B1rF7uIVdp-dxyiZNrmKfVNasR4xmE4A4SlBPA-mipbBOHF3fY824Elk3YtWmPVhRB_zF3tmG9bBOHeWVn4fxwOCzR.; ssxmod_itna2=Yq+xcD9D0iitY7KGHD8Yb4BKRDhAYDBADxroxhnDn93p+hTKDskeDLiiYzvx2EGRQD6ig9iC8Y8Wrt8qhCQEx+rrIde2xbuhiM6IeRtCMcqs=VjlFpmg9zk7XHTTeH1SovwdC9IIyqjUIEE/YW01tlfxAf0zG7K/UEDaIo3gIotvRerXUedt2jjmAruepWoWdPr8icdHwjTtTRNOr6FQ1QaOqMIbRihqOqRLQ7uLiDWmuh3yYYQcSgB64OiAmU6A8igAzIgpRhF0ZtrR8YqEQtwiKBpO9KEUZ41mGzKwK41p0NgujRY27EwDiXmjhnXKQwf10XrDLnXbaKwpYqDNnaGMo2CDEx7Pg=qq7jlxfNc2j0m0PEzp3wD0jiDwQ2Hht4KEAl2/6oZ=Y9jo71LqhoaPnxELF2dFrW5inQmi5=GGp5L15bhIf3cRrcE/I2DLVA5Mmnv4haDG2jiYbrL0x4RD=qrcGegGDQUhxWDkK2q+WbAL2UdkbAy8kcnhxQRD8i4K0DBM=YCBtQAKlS+QDNi0n2wLjhxYalK0SyxD7q0Lwq6pXhiD15+j27v4Q6IuiL=leoDDFqD+PjGADy+GKgi969sYD===; aliyungf_tc=c10607dd0f50873c70f2d2f08431a3ea132d0dcc3fa81c564f94f2daa32b4403; acw_tc=ac11000117126646809334942ef63b2bf747310d1f1a5d06bd9e956ce806d6; Hm_lpvt_f0fbc9a7e7e7f29a55a0c13718e9e542=1712664681"
    }

post_url = 'https://www.csindex.com.cn/csindex-home/index-list/query-index-item?type__1773=mqjOiKBK7KDKAIeGXIeeTRzYm5GIheU3dx'
post_json = json.dumps({"sorter":{"sortField":"null","sortOrder":"null"},"pager":{"pageNum":3,"pageSize":10},"indexFilter":{"ifCustomized":"null","ifTracked":"null","ifWeightCapped":"null","indexCompliance":"null","hotSpot":"null","indexClassify":"null","currency":"null","region":"null","indexSeries":"null","undefined":"null"}})

r= requests.post(post_url, headers=header, data=post_json)
print(r.text)

