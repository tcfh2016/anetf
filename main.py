import os
import datetime as dt
import configparser

import mail.mail as mail

config = configparser.ConfigParser()
script_path = os.path.dirname(os.path.realpath(__file__))
config.read(os.path.join(script_path, 'config.ini'))

print(config.has_section("MailServer"))
print(config.has_option("MailServer", "server"))

reporter = mail.HtmlReporter(
    config.get('MailServer', 'server'), 
    config.get('MailServer', 'port'), 
    config.get('MailServer', 'authcode'),
    dt.date.today()-dt.timedelta(days=1),
    script_path)
reporter.send_email(config.get('MailList', 'from'))
