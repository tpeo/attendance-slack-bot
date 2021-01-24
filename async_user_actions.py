##this file is a asynchronous rewrite of the user_actions.py file
##network calls in gspread were synchronous and taking longer than slack allotted 3 seconds so i re-engineered to shave off just enough time
##hit up @wonathanjong for any questions
import pytz, asyncio, json
from aiogoogle import Aiogoogle
from datetime import datetime, date

service_account_creds = {
    "scopes": [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ],
    **json.load(open('./credentials.json'))
}

#ANYTIME THE SHEET IS EDITED THESE VARIABLES MUST CHANGE
#id of spreadsheet being used as database located in url after /d/
spreadsheet_id = ''
#name of semester spreadsheet where data is stored
semester = 'Spring 2021'

def create_user_handler(user, text):
    return asyncio.run(create_user(user, text))

async def create_user(user, text):
    #initialize google service
    async with Aiogoogle(service_account_creds=service_account_creds) as google:
        sheets_api = await google.discover("sheets", "v4")
        #see if user exists with slack id in "User" database
        name_match = await find_all(google, sheets_api, 'Users', 'B', user)
        if name_match:
            return {'body': "You are already registered in the attendance system.", 'header': "User Exists Already"}
        else:
            #isolate name in text
            name = text.replace("register", "").strip()
            #write user to user table
            await insert_row(google, sheets_api, 'Users', [name, user])
            return {
                'body': f"Registered {name} into attendance system. You can now check into events.",
                'header': "Success 💡"
            }


def check_in_handler(user, text):
    return asyncio.run(check_in(user, text))

async def check_in(user, text):
    #initialize google service
    async with Aiogoogle(service_account_creds=service_account_creds) as google:
        sheets_api = await google.discover("sheets", "v4")
        #concurrently retrieve matched user and event data from google sheets
        matches = await asyncio.gather(
            find_all(google, sheets_api, 'Users', 'B', user),
            find_all(google, sheets_api, 'Events', 'B', text)
        )
        user_match = matches[0]
        event_match = matches[1]
        if not user_match:
            return {
                'body': "Register your account before checking in. Type this into Slack: /tpeo register First_Name Last_Name",
                'header': "Invalid: User Doesn't Exist"
            }
        if not event_match:
            all_events = await get_all_records(google, sheets_api, 'Events')
            return {
                'body': "Use these valid event abbreviations: \n" + '\n'.join([f"{event[0]}: {event[1]}" for event in all_events]),
                'header': "Invalid Event Abbreviation 😳"
            }
        #verify time of check in is within 10 minutes of recurring date
        user_checkin_datetime = adjusted_datetime()
        event_start_time = datetime.strptime(event_match[3], '%I:%M %p').time()
        time_delta = subtract_dates(event_start_time, user_checkin_datetime.time())
        if user_checkin_datetime.strftime('%A') != event_match[2] or (time_delta/60 < -10):
            return {
                'body': f"{event_match[0]} is closed for check in at this time.",
                'header': "Invalid Check In Time 😔"
            }
        #verify they didn't already check in to the event
        #could comment this out and save some time
        unique_checkin_slug = user+event_match[1]+user_checkin_datetime.strftime("%m/%d/%Y")
        attendance_match = await find_all_column(google, sheets_api, semester, 'E', unique_checkin_slug)
        if attendance_match:
            return {
                'body': f"You already checked in!",
                'header': "Invalid Check In"
            }
        #slack id, name, check-in time, event name
        timestamp = get_google_timestamp()
        attendance_obj = [user, user_match[0], timestamp, event_match[0], unique_checkin_slug]
        #add new value to attendance in subsheet
        await insert_row(google, sheets_api, semester, attendance_obj)
        return {
            'body': f"Checked {user_match[0]} into {event_match[0]} at {timestamp}",
            'header': "Success 💡"
        }

### HELPER FUNCTIONS ###

#makes 2 separate calls but saves space by not retrieving the whole sheet
async def find_all_slow(google, sheets_api, sheet_name, column_letter, text):
    #retrieve all values in a certain column
    all_values_request = sheets_api.spreadsheets.values.get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!{column_letter}2:{column_letter}", valueRenderOption='FORMATTED_VALUE', dateTimeRenderOption='FORMATTED_STRING')
    all_values = await google.as_service_account(all_values_request)
    #match the cell by text
    match_loc = -1
    if 'values' in all_values:
        for i, v in enumerate(all_values['values']):
            if v[0] == text:
                match_loc = i+2
    #retrieve matched cell data if applicable
    if match_loc == -1:
        return []
    else:
        match_values_request = sheets_api.spreadsheets.values.get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!{column_letter}{str(match_loc)}", valueRenderOption='FORMATTED_VALUE', dateTimeRenderOption='FORMATTED_STRING')
        match_value = await google.as_service_account(match_values_request)
        return match_value['values']

#makes 2 separate calls but saves space by not retrieving the whole sheet
async def find_all_column(google, sheets_api, sheet_name, column_letter, text):
    #retrieve all values in a certain column
    all_values_request = sheets_api.spreadsheets.values.get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!{column_letter}2:{column_letter}", valueRenderOption='FORMATTED_VALUE', dateTimeRenderOption='FORMATTED_STRING')
    all_values = await google.as_service_account(all_values_request)
    if 'values' in all_values:
        #match the cell by text
        for v in all_values['values']:
            if v[0] == text:
                return v
    return []

#1 call retrieves whole sheet, finds a cell based on text match
async def find_all(google, sheets_api, sheet_name, column_letter, text):
    #retrieve all values in a certain column
    all_values_request = sheets_api.spreadsheets.values.get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}", valueRenderOption='FORMATTED_VALUE', dateTimeRenderOption='FORMATTED_STRING')
    all_values = await google.as_service_account(all_values_request)
    #match the specified cell value by text
    value_index = ord(column_letter) - 65 #this will break if column letter is beyond Z
    if 'values' in all_values:
        for v in all_values['values']:
            if v[value_index] == text:
                return v
    #if no match return empty list
    return []

#gets the value of a row
async def row_values(google, sheets_api, sheet_name, range):
    request = sheets_api.spreadsheets.values.get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!{range}", valueRenderOption='FORMATTED_VALUE', dateTimeRenderOption='FORMATTED_STRING')
    records = await google.as_service_account(request)
    return records['values'][0]

#retrieves all values of a sheet
async def get_all_records(google, sheets_api, sheet_name):
    request = sheets_api.spreadsheets.values.get(spreadsheetId=spreadsheet_id, range=sheet_name, valueRenderOption='FORMATTED_VALUE', dateTimeRenderOption='FORMATTED_STRING')
    records = await google.as_service_account(request)
    return records['values']

#inserts new row at the bottom of a sheet
async def insert_row(google, sheets_api, sheet_name, data):
    value_range_body = {
        "range": sheet_name,
        "majorDimension": 'ROWS',
        "values": [data]
    }
    request = sheets_api.spreadsheets.values.append(range=sheet_name, spreadsheetId=spreadsheet_id, valueInputOption='RAW', insertDataOption='OVERWRITE', json=value_range_body)
    return await google.as_service_account(request)

def get_iso_timestamp(timezone="America/Chicago"):
    return datetime.utcnow().replace(tzinfo=pytz.UTC).astimezone(pytz.timezone(timezone)).isoformat()

def adjusted_datetime(timezone="America/Chicago"):
    return datetime.utcnow().replace(tzinfo=pytz.UTC).astimezone(pytz.timezone(timezone))

#returns dates in this format 9/26/2008 15:00:00
def get_google_timestamp(timezone="America/Chicago"):
    return adjusted_datetime(timezone=timezone).strftime("%m/%d/%Y %H:%M:%S")

def subtract_dates(start_time, stop_time):
    placeholder_date = date(1, 1, 1)
    datetime1 = datetime.combine(placeholder_date, start_time)
    datetime2 = datetime.combine(placeholder_date, stop_time)
    return (datetime1 - datetime2).total_seconds()
