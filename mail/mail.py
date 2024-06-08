
# -*- coding:utf-8 -*-
"""
Date: 2024-05-03
Desc: 邮件报告
"""

import os
import smtplib
import pandas as pd
import datetime as dt
from email.message import EmailMessage

class HtmlReporter(object):
    def __init__(self, server, port, authcode, date, script_path):
        self._server = server
        self._port = port
        self._authcode = authcode
        self._date = date   
        self._script_path = script_path
        self._head = '''
        <!DOCTYPE html>
        <html lang="en" dir="ltr">
          <head>
            <meta charset="utf-8">
            <title></title>
            <style media="screen">
              body {
                background-color: LightYellow;
                width: 900px;
              }
              header {
                text-align: center;
              }
              div {
                text-align: center;
              }
              section {
                height: 50px;
                text-align: center;
              }
              article {
                font-size: 12px;
                text-align: center;
                color: blue;
                width: 900px;
                margin-left: auto;
                margin-right: auto;
              }
              figure {
                background-color: Cornsilk;
                width: 900px;
                margin-left: auto;
                margin-right: auto;
              }
              footer {
                text-align: center;
                padding: 3px;
                background-color: white;
                color: blue;
              }
              table {
                width: 900px;
                text-align:right;
                border-collapse: collapse;
                margin-left: auto;
                margin-right: auto;
              }
              th {
                background-color: Brown;
                color: white;
              }
              .img {
                width: 900px;
              }
              .low {
                background-color: lightgreen;
              }
              .high {
                background-color: tomato;
              }
            </style>
          </head>
          <body>
        '''
        self._tail = '''
            <footer>
              <p> 以上信息仅供参考。 </p>
            </footer>
          </body>
        </html>
        '''

    def get_eva_status(self, pe, pe_percentile):
        if (pe < 15 or pe_percentile < 0.10):
            return "low"

        if (pe > 50 or pe_percentile > 0.90):
            return "high"
        
    def construct_ETF_list(self, etf, series):
        etf_table = """
        <header>
            <h3>ETF海选列表-{}</h3>
        </header>
        <div>
            <table>
              <tr>
                <th>基金名称</th>
                <th>基金代码</th>
                <th>指数名称</th>
                <th>指数代码</th>
                <th>市盈率</th>
                <th>市盈率百分位</th>
              </tr>
        """.format(series)

        for i in range(len(etf)):
            pe = etf['市盈率'].iloc[i]
            pe_percentile = etf['市盈率百分位'].iloc[i]
            eva_status = self.get_eva_status(pe, pe_percentile)

            etf_table += """
            <tr  class="{}">
                <td>{}</td>
                <td>{}</td>
                <td>{}</td>
                <td>{}</td>
                <td>{}</td>
                <td>{}</td>
            </tr>
            """.format(eva_status,
                       etf['ETF名称'].iloc[i],
                       etf['ETF代码'].iloc[i],
                       etf['指数名称'].iloc[i],
                       str(etf['指数代码'].iloc[i]),
                       str(round(pe, 2)),
                       str(round(pe_percentile * 100, 2)) + '%')

        etf_table += """
        </table>
        </div>
        <section> </section>
        """

        return etf_table

    def send_email(self, sender):
        msg = EmailMessage()

        # 填充邮件头部
        msg['Subject'] = 'ETF海选列表 - ' + str(self._date)
        msg['From'] = sender
        msg['To'] = ['lianbch@163.com']

        etfs_broad = pd.read_csv(
            os.path.join(self._script_path, 'mail', 'etf_broad_sorted.csv'), 
            usecols=['ETF名称', 'ETF代码', '指数名称', '指数代码', '市盈率', '市盈率百分位'])
        etfs_other = pd.read_csv(
            os.path.join(self._script_path, 'mail', 'etf_other_sorted.csv'), 
            usecols=['ETF名称', 'ETF代码', '指数名称', '指数代码', '市盈率', '市盈率百分位'])

        # 填充邮件正文
        html = self._head \
               + self.construct_ETF_list(etfs_broad, '宽基') \
               + self.construct_ETF_list(etfs_other, '其他') \
               + self._tail
        msg.set_content(html, subtype='html')
        
        # 发送邮件
        try:
            mail_server = smtplib.SMTP_SSL(self._server, port=self._port)
            mail_server.login(sender, self._authcode)
            mail_server.send_message(msg)
        except smtplib.SMTPException as ex:
            print("Error: send failure = ", ex)

if __name__ == '__main__':
    date = dt.date.today()-dt.timedelta(days=1)
    reporter = HtmlReporter('xxx', 465, 'xxx', date)
    sender = 'xxx'
    receiver = ['lianbch@163.com']
    reporter.send_email(sender) 
