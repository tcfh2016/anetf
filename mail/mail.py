
# -*- coding:utf-8 -*-
"""
Date: 2024-05-03
Desc: 邮件报告
"""

import os
import logging
import smtplib
import pandas as pd
import datetime as dt
from email.message import EmailMessage

logger = logging.getLogger(__name__)

# 与 pe.py 的分类保持一致：(分类键，邮件展示名)
categories = [
    ('crossborder', '跨境股票'),
    ('broad', '宽基指数'),
    ('sector', '行业股票'),
    ('theme', '主题投资'),
    ('strategy', '策略指数'),
    ('commodity', '商品'),
    ('bond', '固定收益'),
]

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

    def get_eva_status(self, value, percentile, value_type):
        if pd.isna(percentile):
            return "normal"

        # 市盈率阈值只对PE类型有意义（且需为正值），点位类只看百分位
        if value_type == 'PE' and pd.notna(value) and 0 < value < 15:
            return "low"
        if percentile < 0.10:
            return "low"

        if value_type == 'PE' and pd.notna(value) and value > 50:
            return "high"
        if percentile > 0.90:
            return "high"

        return "normal"
        
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
                <th>估值类型</th>
                <th>估值</th>
                <th>估值百分位</th>
              </tr>
        """.format(series)

        for i in range(len(etf)):
            value_type = etf['估值类型'].iloc[i]
            value = etf['估值'].iloc[i]
            percentile = etf['估值百分位'].iloc[i]
            eva_status = self.get_eva_status(value, percentile, value_type)

            value_str = str(round(value, 2)) if pd.notna(value) else '-'
            pct_str = str(round(percentile * 100, 2)) + '%' if pd.notna(percentile) else '-'
            type_str = value_type if isinstance(value_type, str) and value_type else '-'

            etf_table += """
            <tr  class="{}">
                <td>{}</td>
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
                       type_str,
                       value_str,
                       pct_str)

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

        etf_cols = ['ETF名称', 'ETF代码', '指数名称', '指数代码', '估值类型', '估值', '估值百分位']
        etf_tables = []
        for key, label in categories:
            csv_path = os.path.join(self._script_path, 'mail', 'etf_{}_sorted.csv'.format(key))
            if not os.path.exists(csv_path):
                logger.warning('ETF list not found: {}'.format(csv_path))
                continue
            etfs = pd.read_csv(csv_path, usecols=etf_cols)
            etf_tables.append(self.construct_ETF_list(etfs, label))

        # 填充邮件正文
        html = self._head + ''.join(etf_tables) + self._tail
        msg.set_content(html, subtype='html')
        
        # 发送邮件
        try:
            mail_server = smtplib.SMTP_SSL(self._server, port=self._port)
            mail_server.login(sender, self._authcode)
            mail_server.send_message(msg)
            logger.info('Email sent successfully.')
        except smtplib.SMTPException as ex:
            logger.error("Error: send failure = %s", ex)

if __name__ == '__main__':
    date = dt.date.today()-dt.timedelta(days=1)
    reporter = HtmlReporter('xxx', 465, 'xxx', date)
    sender = 'xxx'
    receiver = ['lianbch@163.com']
    reporter.send_email(sender) 
