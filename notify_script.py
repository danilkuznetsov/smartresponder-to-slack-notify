# coding: utf-8
import datetime
import sys
import urllib
import urllib2
from hashlib import md5

import requests

try:
    import json
except ImportError:
    import simplejson as json

API_URL = 'http://api.smartresponder.ru/subscribers.html'
REQUEST_ENCODING = 'utf8'
API_ID = '<dumy api id>'
API_SECRET = 'dumy secret key'
CHECK_TIMEOUT = 15*60
SLACK_WEBHOOK_URL = '<dumy slack url>'
DELIVERIES_ID = '<dumy id>'


class SMRError(Exception):
    __slots__ = ["error"]

    def __init__(self, error_data):
        self.error = error_data
        Exception.__init__(self, str(self))

    @property
    def code(self):
        return self.error['error_code']

    @property
    def description(self):
        return self.error['error_msg']

    @property
    def params(self):
        return self.error['request_params']

    def __unicode__(self):
        return "Error(code = '%s', description = '%s', params = '%s')" % (self.code, self.description, self.params)

    def __str__(self):
        return "Error(code = '%s', params = '%s')" % (self.code, self.params)


def encode(data):
    if isinstance(data, (dict, list, tuple)):
        return json.dumps(data, ensure_ascii=False, encoding=REQUEST_ENCODING)

    if isinstance(data, unicode):
        return data.encode(REQUEST_ENCODING)

    return data


class SmartAPI(object):
    def __init__(self, api_id=None, api_secret=None, url=None):
        if not (api_id and api_secret or url):
            raise ValueError("Arguments api_id and api_secret or token are required")

        self.api_id = api_id
        self.api_secret = api_secret
        self.request_url = url

    def _make_signature(self, params):
        if isinstance(params, dict):
            params = params.items()
        param_str = ":".join(
                ["%s=%s" % (str(key), encode(value)) for key, value in params] +
                ["%s=%s" % ('password', self.api_secret)])
        return md5(param_str).hexdigest()

    def send_request(self, params):
        payload = [('format', 'json')]

        payload += params[:]

        payload += [('api_id', self.api_id)]
        sig = self._make_signature(payload)
        payload += [('hash', sig)]

        headers = {"Accept": "application/json",
                   "Content-Type": "application/x-www-form-urlencoded"}

        values = urllib.urlencode(payload)

        r = requests.post(self.request_url, data=values, headers=headers)

        if not (200 <= r.status_code <= 299):
            raise SMRError({
                'error_code': r.status_code,
                'error_msg': "HTTP error",
                'request_params': payload,
            })

        result = json.loads(r.text, strict=False)
        if "error" in result:
            raise SMRError({
                'error_code': result['error']['code'],
                'error_msg': result['error']['message'],
                'request_params': payload,
            })
        return result


class Slack():
    def __init__(self, url=""):
        self.url = url
        self.opener = urllib2.build_opener(urllib2.HTTPHandler())

    def notify(self, **kwargs):
        """
        Send message to slack API
        """
        return self.send(kwargs)

    def send(self, payload):
        """
        Send payload to slack API
        """
        payload_json = json.dumps(payload)
        data = urllib.urlencode({"payload": payload_json})
        req = urllib2.Request(self.url)
        response = self.opener.open(req, data.encode('utf-8')).read()
        return response.decode('utf-8')


if __name__ == "__main__":
    now = datetime.datetime.now()
    yesterday = now - datetime.timedelta(4)
    slack = Slack(url=SLACK_WEBHOOK_URL)

    sys.stdout.write(u'[INFO] {now}\nsend request to smartresponder on date={yesterday}\n'.format(now=str(now),
                                                                                                  yesterday=str(
                                                                                                          yesterday)))
    smart_api = SmartAPI(api_id=API_ID, url=API_URL, api_secret=API_SECRET)
    search_clients = [('action', 'list'), ('fields', 'id,email,phones,state,date_added,first_name,deliveries'),
                      ('search[date_from_day]', yesterday.day),
                      ('search[date_from_month]', yesterday.month), ('search[date_from_year]', yesterday.year),
                      ('search[deliveries_ids]', DELIVERIES_ID), ('f_included_in_deliveries', '1')]
    try:
        response = smart_api.send_request(search_clients)
        if isinstance(response, dict) and response.get('result', 0):
            clients = response.get('list', None)
            if clients.get('count', 0) > 0:
                for client in clients.get('elements', None):
                    for deliveries in client.get('deliveries', []):
                        if deliveries.get('id', '') == DELIVERIES_ID:
                            client_added_date = datetime.datetime.strptime(
                                deliveries.get('date_added', '01.01.1970 00:00:00'),
                                "%d.%m.%Y %H:%M:%S")
                            if (now - client_added_date).total_seconds() <= CHECK_TIMEOUT:
                                slack.notify(
                                        text=u'[New lead] {client_added_date}\nname= {name}\nemail= {email}\nphone= {phone}\nstatus= {status}\n'.format(
                                                client_added_date=client_added_date,
                                                name=client.get('first_name', 'Anonymous'),
                                                email=client.get('email', 'no email'),
                                                phone=client.get('phones', 'no phone'),
                                                status=client.get("state", "no state")))
            else:
                sys.stdout.write('No leads\n')
    except SMRError as e:
        slack.notify(text=u'[ERROR] {now}\n{error}\n'.format(now=now, error=e.error))
