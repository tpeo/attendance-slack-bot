import json, time, urllib, hmac, hashlib, re, random
from modules import decimalencoder, slack_secrets, slack_help
import async_user_actions

''' MAIN CODE '''

#handles slack command request
def parse_request(event, context):
    if not verifySlackRequest(event):
        return
    data = parse_payload(event['body'])
    user = {
        'workspace': data['team_domain'],
        'team_id': data['team_id'],
        'user_name': data['user_name']
    }
    return router(data, user)

#routes to whatever action should be done
def router(slack_request_data, slack_user):
    text = clean_text(slack_request_data)
    lowercased_text = text.lower()
    data = {}
    if 'checkin' in text:
        data = async_user_actions.check_in_handler(slack_user['user_name'], lowercased_text.replace("checkin", "").strip())
        msg = slack_message(slack_user['user_name'], data['body'], data['header'], msg_type="ephemeral" if "Invalid" in data['header'] else 'in_channel')
        return msg
    elif 'register' in text:
        data = async_user_actions.create_user_handler(slack_user['user_name'], text)
        msg = slack_message(slack_user['user_name'], data['body'], data['header'], msg_type="ephemeral")
        return msg
    else:
        return http_response(slack_help.help)

''' HELPER FUNCTIONS '''

#returns message given data
def slack_message(user, body, header, msg_type="ephemeral"):
    slack_emojis = [":flushed:", ":smile:", ":musical_note:", ":musical_keyboard:", ":musical_score:", ":bangbang:", ":rocket:", ":candy:", ":headphones:", ":violin:", ":microphone:", ":bomb:", ":tada:", ":video_camera:", ":speaker:", ":radio:"]
    response_message = create_basic_message(
        header=f"<@{user}> *{header}* " + random.choice(slack_emojis),
        body=body,
        type= msg_type
    )
    return http_response(response_message)

#verifies that request comes from the slack app
def verifySlackRequest(event):
    headers = event['headers']
    request_body = event['body']
    timestamp = headers['X-Slack-Request-Timestamp']
    if abs(time.time() - float(timestamp)) > 60 * 5:
        return False
    sig_basestring = 'v0:' + timestamp + ':' + request_body
    my_signature = 'v0=' + hmac.new(
            slack_secrets.slack_signing_secret,
            sig_basestring.encode(),
            hashlib.sha256
        ).hexdigest()
    slack_signature = headers['X-Slack-Signature']
    return hmac.compare_digest(my_signature, slack_signature)

def http_response(data):
    return {
        "statusCode": 200,
        "headers": {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Credentials': True,
            'Content-Type': 'application/json'
        },
        "body": json.dumps(data, cls=decimalencoder.DecimalEncoder)
    }

#turns slack payload into a readable dictionary
def parse_payload(payload):
    #break apart slack payload
    body = urllib.parse.unquote_plus(payload).split('&')
    #create dictionary from slack payload
    data = {}
    for payloadItem in body:
        item = payloadItem.split('=')
        data[item[0]] = item[1]
    return data

#removes user mentions from slack text
def clean_text(data):
    txt = data['text'].replace("|", "%")
    #use regex to find users mentioned in slack message
    mentioned = re.findall(r'<@[\w\.]+%?[\w\.]+>', txt)
    #clear all usernames from string
    for username in mentioned:
        txt = re.sub(username, "", txt)
    return txt.strip()

def create_basic_message(header="", body="", type="ephemeral"):
    message = {
        "response_type": type,
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": body
                }
            }
        ]
    }
    #add header if necessary
    if header !="":
        message['blocks'].insert(0,
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": header
                }
            }
        )
    return message
