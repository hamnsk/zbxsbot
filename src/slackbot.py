#!/usr/bin/env python
# coding: utf-8

import os
import time
import re
import random
import requests
import sys
from slackclient import SlackClient
from pyzabbix import ZabbixAPI


import logging
logging.basicConfig()

# constants
RTM_READ_DELAY = 1
MENTION_REGEX = "^<@(|[WU].+?)>(.*)"
slack_token = os.getenv('ZBXSBOT_SLACK_TOKEN', 'your_slack_app_token_here')
zbx_user = os.getenv('ZBXSBOT_ZABBIX_USER', 'username_for_zabbix_login')
zbx_pass = os.getenv('ZBXSBOT_ZABBIX_PASSWORD', 'password_for_zabbix_login')
zbx_host = os.getenv('ZBXSBOT_ZABBIX_HOST', 'https://zabbix_url')
slack_client = SlackClient(slack_token)

users = {}
for user in slack_client.api_call("users.list")['members']:
    users[user['id']] = user['name']
ims = []
for i in slack_client.api_call("im.list")['ims']:
    ims.append(i['id'])


def helper(params):
    return "Я понимаю следующие команды:", "\
    Команды Zabbix_bot:\n\
    *@Zabbix_bot h[elp]* - помощь\n\
    *@Zabbix_bot t[riggers] [MIN_SEVERITY]* - текущие триггеры в заббикс (где MIN_SEVERITY одна из i[nformation], w[arning], a[verage], h[igh], d[isaster]) - по умолчанию disaster\n\
    *@Zabbix_bot g[raph] ИД_триггера* - Выводит график по триггеру за последний час, есть варинты g1, g3, g6, g12, g24\n\
    *@Zabbix_bot ack ИД_триггера Сообщение* - проставить ACK по триггеру\n\
    ", "#1241a6"


def quote(params):
    r = requests.get('https://randstuff.ru/joke/', timeout=5, allow_redirects=True, verify=False)
    content = r.content.split('<td>')
    quote = content[1].split('</td>')
    return "Цитата дня:", quote[0], "#1241a6"


def trista(params):
    return "CENSORED!!!", "А, ну-ка не безобразничай!!! :joy:", "#1241a6"


def lenta(params):
    r = requests.get('https://lenta.ru/rss', timeout=5, allow_redirects=True, verify=False)
    content = r.content.split("<item>")
    news = {}
    for line in content[1:]:
       m = re.match(".*<title>(.*)</title>.*<link>(.*)</link>.*", line.replace("\n", ""))
       if m:
          news[m.group(1)] = m.group(2)
    r = random.choice(news.keys())

    return "Последние новости:", "%s \n %s" % (r, news[r]), "#1241a6"


def zabbix_triggers(params):
    z = ZabbixAPI(zbx_host)
    z.session.verify = False
    z.login(zbx_user, zbx_pass)
    severity = {'information': 1,
                'warning': 2,
                'average': 3,
                'high': 4,
                'disaster': 5,
                'i': 1,
                'w': 2,
                'a': 3,
                'h': 4,
                'd': 5}
    sv = params.replace(' ', '').lower()
    min_severity = severity.get(sv, 5)
    MIN_SEVERITY = {1: 'information',
                    2: 'warning',
                    3: 'average',
                    4: 'high',
                    5: 'disaster'}
    out = ""
    trigger_dict = {}

    for trigger in z.trigger.get(min_severity=min_severity,
                                 active=1,
                                 monitored=1,
                                 only_true=1,
                                 output='extend',
                                 expandDescription=1,
                                 selectHosts='extend',
                                 selectItems='extend',
                                 withLastEventUnacknowledged=1):

        for i in trigger['items']:
            for h in trigger['hosts']:
                if trigger['description'] not in trigger_dict:
                    trigger_dict[trigger['description']] = [{'hostname': h['name'], 'triggerid': trigger['triggerid']}]
                else:
                    trigger_dict[trigger['description']].append({'hostname': h['name'], 'triggerid': trigger['triggerid']})

    for o in trigger_dict:
        tr_hosts = []
        for v in trigger_dict[o]:
            tr_hosts.append(v['hostname'] + ' [{}]'.format(v['triggerid']))
        out=out+"*%s* \n - %s\n" % (o,"\n - ".join(tr_hosts))
    if out == "": out = "No  triggers with min_severity='" + MIN_SEVERITY[min_severity] + "' found"
    return "Текущие триггеры:", out, "#fc0303"


def get_graph(graphid, period):
    zapi = ZabbixAPI(zbx_host)
    zapi.session.verify = False
    zapi.login(zbx_user, zbx_pass)
    loginurl = zbx_host + ""
    logindata = {'autologin': '1', 'name': zbx_user, 'password': zbx_pass, 'enter': 'Sign in'}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 5.1; rv:31.0) Gecko/20100101 Firefox/31.0',
               'Content-type': 'application/x-www-form-urlencoded'}
    session = requests.session()
    login = session.post(loginurl, params=logindata, headers=headers, verify=False)
    try:
        if session.cookies['zbx_sessionid']:
            graphurl = zbx_host + "/"+"chart.php?from=now-"+str(period)+"h&to=now&itemids="+str(graphid)+"&type=0&profileIdx=web.item.graph.filter"
            graphreq = session.get(graphurl, verify=False)
            return graphreq.content, graphurl
    except:
        print("Error: Could not log in to retrieve graph")
        return 0


def get_graph_id(params, period):
    z = ZabbixAPI(zbx_host)
    z.session.verify = False
    z.login(zbx_user, zbx_pass)
    params = params.split(' ')
    if len(params) > 1:
        for item in params:
            trg = z.trigger.get(triggerids=item, output='extend', selectItems='extend')
            name = trg[0]['items'][0]['name']
            desc = trg[0]['items'][0]['description']
            return get_graph(int(trg[0]['items'][0]['itemid']), period), name, desc
    else:
        trg = z.trigger.get(triggerids=params[0], output='extend', selectItems='extend')
        try:
            name = trg[0]['items'][0]['name']
            desc = trg[0]['items'][0]['description']
            graph, graphurl = get_graph(int(trg[0]['items'][0]['itemid']), period)
            return graph, graphurl, name, desc
        except:
            return 0


def set_ack(params, user):
    params = params.split()
    z = ZabbixAPI(zbx_host)
    z.session.verify = False
    z.login(zbx_user, zbx_pass)
    events = z.event.get(objectids=params[0], acknowledged=False)
    msg = ' '.join(params[1:]).encode('utf-8')
    ack_message = "[{user}] {msg}".format(user=user, msg=msg)
    events_list = []
    for i in events:
        events_list.append(int(i['eventid']))
    try:
        z.event.acknowledge(eventids=max(events_list), action=6, message=ack_message)
        return '<@{}> Сделано!'.format(user), '#37a612'
    except:
        return '<@{}> Не могу! Сам проставь!'.format(user), '#fc0303'


commands = {
    'help': helper,
    'h': helper,
    '300': trista,
    'lenta': lenta,
    'что': lenta,
    'как': lenta,
    'новости': lenta,
    'нового': lenta,
    't': zabbix_triggers,
    'triggers': zabbix_triggers,
    'quote': quote,
    'q': quote,
    'graph': 1,
    'g': 1,
    'g1': 1,
    'g3': 3,
    'g6': 6,
    'g12': 12,
    'g24': 24,
    'ack': set_ack,
}


def parse_bot_commands(slack_events):
    for event in slack_events:
        if event["type"] == "message" and not "subtype" in event:
            user_id, message = parse_direct_mention(event["text"])
            if user_id == starterbot_id:
                return message, event["channel"]
    return None, None


def parse_direct_mention(message_text):
    matches = re.search(MENTION_REGEX, message_text)
    return (matches.group(1), matches.group(2).strip()) if matches else (None, None)


def handle_command(command, channel, user):
    default_response = "Не понимаю о чем вы, попробуйте набрать команду *help*."
    helper_text = "Нипанятна :see_no_evil:"
    color = "#1241a6"

    try:
        msg_in = command.split()
        cmd = msg_in[0]
        params = ' '.join(msg_in[1:])
    except ValueError:
        params = ''
        cmd = command
    if cmd in ['g', 'graph', 'g3', 'g6', 'g12', 'g24']:
        result,  graphurl, g_name, g_desc = get_graph_id(params, commands.get(cmd))
        if result:
            slack_client.api_call(
                "files.upload",
                channels=channel,
                file=result,
                title=g_name.encode('utf-8'),
                initial_comment="<@{}> Ваш график: ".format(user) + g_name.encode('utf-8'))
    elif cmd in ['ack']:
        response, color = set_ack(params, user)
        helper_text = 'Результат установки ack:'
        slack_client.api_call(
            "chat.postMessage",
            channel=channel,
            attachments=[{"title": helper_text,
                          "text": response or default_response,
                          "fallback": helper_text,
                          "callback_id": "bp_zbx_alerts",
                          "color": color,
                          "attachment_type": "default"}]
        )
    elif cmd in commands:
        helper_text, response, color = commands[cmd](params)
        slack_client.api_call(
            "chat.postMessage",
            channel=channel,
            attachments=[{"pretext": '<@{}>'.format(user) + helper_text, "text": response or default_response, "color": color, "attachment_type": "default"}]
        )
    else:
        slack_client.api_call(
            "chat.postMessage",
            channel=channel,
            attachments=[{"pretext": '<@{}>'.format(user) + helper_text, "text": default_response, "color": color, "attachment_type": "default"}]
        )


if __name__ == "__main__":
    try:
        if slack_client.rtm_connect(with_team_state=False):
            print("Starter Bot connected and running!")
            starterbot_id = slack_client.api_call("auth.test")["user_id"]
            while True:
                msg = slack_client.rtm_read()
                print(msg)
                if len(msg) > 0 and msg[0]['type'] == 'message':
                    try:
                        user = users.get(msg[0]['user'], msg[0]['user'])
                    except KeyError:
                        user = 'Zabbix_bot'
                    command, channel = parse_bot_commands(msg)
                    if command:
                        handle_command(command, channel, user)
                time.sleep(RTM_READ_DELAY)
        else:
            print("Connection failed. Exception traceback printed above.")
            sys.exit()
    except KeyboardInterrupt:
        sys.exit()
