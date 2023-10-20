import typer
import rich
from rich.console import Console
from rich.pretty import pprint
import requests
from fillpdf import fillpdfs
import json
import secrets
import os
import re

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import msal

# Get Graph API token with user creds
def get_graph_token(configjson: str = "creds/graph.json"):
    # Load config file
    try:
        with open(configjson) as f:
            config = json.load(f)
    except FileNotFoundError:
        raise Exception("Could not find graph file")

    msapp = msal.PublicClientApplication(config["client_id"], authority=config["authority"])

    res = msapp.acquire_token_interactive(config["scope"])

    try:
        return res["access_token"]
    except KeyError:
        raise Exception("Could not get Graph API token")
    
def google_auth():
    SCOPES = ['https://www.googleapis.com/auth/admin.directory.user', 'https://www.googleapis.com/auth/admin.directory.group']
    # Check if we have a token already
    creds = None

    if os.path.exists('creds/token.json'):
        creds = Credentials.from_authorized_user_file('creds/token.json', SCOPES)

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'creds/appcreds.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('creds/token.json', 'w') as token:
            token.write(creds.to_json())

    return creds

# Create a user on google workspace
def create_google_user(givenName: str, familyName:str, password: str, domain: str):    
    # Start Google OAuth flow
    creds = google_auth()

    # Create service object for calling the Admin SDK Directory API
    service = build("admin", "directory_v1", credentials=creds)

    # Create username in form of firstname.lastname@integriculture.com in lowrcase
    username = f"{givenName.lower()}.{familyName.lower()}@{domain}"

    # Create user
    user = { 
        "primaryEmail": username,
        "name": {
            "givenName": givenName,
            "familyName": familyName,
        },  
        "password": password,
        "changePasswordAtNextLogin": True,
        "includeInGlobalAddressList": True
    }

    # Call the Admin SDK Directory API
    results = service.users().insert(body=user).execute()

    return results

# Get Google Directory Groups
def get_google_groups():
    # Start Google OAuth flow
    creds = google_auth()

    # Create service object for calling the Admin SDK Directory API
    service = build("admin", "directory_v1", credentials=creds)

    # Call the Admin SDK Directory API
    results = service.groups().list(domain="integriculture.com").execute()

    return results["groups"]


# Add user to Google Directory Group
def add_to_google_group(group_email: str, user: str):
    # Start Google OAuth flow
    creds = google_auth()

    # Create service object for calling the Admin SDK Directory API
    service = build("admin", "directory_v1", credentials=creds)

    # Call the Admin SDK Directory API
    results = service.members().insert(groupKey=group_email, body={"email": user}).execute()

    return results


# Create a user on AzureAD
def create_azure_user(token: str, givenName: str, familyName:str, password: str, domain: str):
    api_endpoint = "https://graph.microsoft.com/v1.0/users"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Request body
    d = {
        "accountEnabled": True,
        "displayName": f"{givenName} {familyName}",
        "mailNickname": f"{givenName.lower()}.{familyName.lower()}",
        "userPrincipalName": f"{givenName.lower()}.{familyName.lower()}@{domain}",
        "passwordProfile": {
            "forceChangePasswordNextSignIn": True,
            "password": password
        }
    }

    # POST request to create user
    response = requests.post(api_endpoint, headers=headers, json=d)
    return response

# Check O365 license count
def check_o365_license_count(token: str) -> list:
    api_endpoint = "https://graph.microsoft.com/v1.0/subscribedSkus"
    headers = {"Authorization": f"Bearer {token}"}

    # GET request to get license count
    response = requests.get(api_endpoint, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Could not get license count. Error: {response.status_code} {response.text}")
    
    # Parse response
    tally = [0, 0]
    for sku in json.loads(response.text)["value"]:
        if re.match("O365*", sku["skuPartNumber"]):
            tally[0] = sku["prepaidUnits"]["enabled"] - sku["consumedUnits"] + tally[0]
        elif sku["skuPartNumber"] == "EMS":
            tally[1] = sku["prepaidUnits"]["enabled"] - sku["consumedUnits"] + tally[1]

    return tally

# Fill out welcome pdf
def fill_welcome_pdf(givenName: str, familyName:str, password: str, gdomain: str, msdomain: str, ggroup: list):
    if len(ggroup) != 0:
        group_str = ggroup[0][1]
        if len(ggroup) > 1:
            for g in ggroup:
                group_str = f"{group_str}, {g[1]}"
    else:
        group_str = ""

    d = {'uname': f"{givenName} {familyName}",'guser': f"{givenName.lower()}.{familyName.lower()}@{gdomain}", 'gpass': f"{password}", 'msuser': f"{givenName.lower()}.{familyName.lower()}@{msdomain}", 'mspass': f"{password}", 'ggroup': f"{group_str}"}
    fillpdfs.write_fillable_pdf(input_pdf_path = "assets/welcome_v2.pdf", output_pdf_path = f"{givenName}_{familyName}_welcome.pdf", data_dict= d, flatten = True)



app = typer.Typer(help="Awesome CLI user manager.")

# Argument to create a user
@app.command(help = "Create a user")
def add(password: str = None, gdomain: str = "integriculture.com", msdomain: str = "integriculture.net"):
    givenname = typer.prompt("Enter given name")
    familyname = typer.prompt("Enter family name")
    # Capitalize names
    givenname = givenname.capitalize()
    familyname = familyname.capitalize()
    # If password is None, create random password
    if password == None:
        password = secrets.token_urlsafe(13)
    # Confirm username
    console.print(f"Username will be {givenname.lower()}.{familyname.lower()}@{gdomain} for {givenname} {familyname}")
    usercorrect = typer.confirm("Is this correct?", default=True)
    if not usercorrect:
        raise typer.Exit(code=1)

    # Get Google Workspaces groups list and print
    groups = get_google_groups()
    for i in range(len(groups)):
        console.print(f"[{i}] {groups[i]['name']} ({groups[i]['email']})")
    # Prompt for group
    addgroup = typer.prompt("Which group should the user be added to? (Separate multiple groups with comma)", default = "")
    # Split groups
    grouplist = addgroup.split(",")
    addgroup = []
    if grouplist[0] != "":
        for g in grouplist:
            addgroup.append([groups[int(g)]["email"], groups[int(g)]["name"]])

    # Create user on google workspace
    console.print(f"☑️ Creating user on Google Workspace")
    try:
        guser = create_google_user(givenname, familyname, password, gdomain)
    except Exception as e:
        console.print(f"❌ Failed to create user on Google Workspace")
        console.print(e)
        raise typer.Exit(code=1)

    # Check return
    if guser:
        console.print(f"✅ User {guser['primaryEmail']} created on Google Workspace")

    # Add user to groups
    for group in addgroup:
        console.print(f"☑️ Adding user to group {group[1]}")
        try:
            add_to_google_group(group[0], guser["primaryEmail"])
        except Exception as e:
            console.print(f"❌ Failed to add user to group {group[1]}")
            console.print(e)
            raise typer.Exit(code=1)
        console.print(f"✅ User added to group {group[1]}")

    console.rule("Google Workspace done!")

    # Get Graph API token
    token = get_graph_token()

    # Check O365 license count
    while True:
        console.print(f"☑️ Checking MSFT license count")
        try:
            tally = check_o365_license_count(token)
        except Exception as e:
            console.print(f"❌ Failed to check O365 license count")
            console.print(e)
            raise typer.Exit(code=1)
        
        no_license = False
        if tally[0] < 1:
            console.print(f"❌ {tally[0]} O365 licenses available")
            no_license = True
        elif tally[1] < 1:
            console.print(f"❌ {tally[1]} EMS licenses available")
            no_license = True
        
        if no_license:
            console.print(f"Goto https://admin.microsoft.com/#/subscriptions to add more licenses")
            check = typer.prompt("[R]echeck license count or [I]gnore?", default="R").lower()

            if check == "r":
                continue
            elif check == "i":
                console.print(f"☑️ Ignoring license deficiency")
                break
        else:
            console.print(f"✅ MSFT licenses available")
            break

    # Create user on AzureAD
    console.print(f"☑️ Creating user on AzureAD")
    msuser = create_azure_user(token, givenname, familyname, password, msdomain)

    # Check return
    if msuser.status_code == 201:
        console.print(f"✅ User created on AzureAD")
    elif msuser.status_code == 400 and json.loads(msuser.text)["error"]["message"] == "Another object with the same value for property userPrincipalName already exists.":
        console.print(f"❌ User already exists on AzureAD")
    else:
        console.print(f"❌ Failed to create user on AzureAD. Error: {msuser.status_code} {msuser['message']}")
        raise typer.Exit(code=1)
    
    console.rule("AzureAD done!")
    
    # Fill out welcome pdf
    console.print(f"☑️ Filling out welcome pdf")
    fill_welcome_pdf(givenname, familyname, password, gdomain, msdomain, addgroup)
    console.print(f"✅ Welcome pdf filled out")

    console.rule("All done!")

# List groups
@app.command(help = "List groups")
def listgroups():
    groups = get_google_groups()
    for group in groups:
        pprint({"Name": group["name"], "Email": group["email"]}, expand_all=True)


if __name__ == "__main__":
    console = Console()
    app()