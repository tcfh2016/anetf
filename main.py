import datetime as dt
import configparser

import mail.mail as mail

config = configparser.ConfigParser()
config.read('config.ini')

print(config.has_section("MailServer"))
print(config.has_option("MailServer", "server"))

reporter = mail.HtmlReporter(
    config.get('MailServer', 'server'), 
    config.get('MailServer', 'port'), 
    config.get('MailServer', 'authcode'),
    dt.date.today()-dt.timedelta(days=1))
#reporter.send_email(config.get('MailList', 'from'))  


