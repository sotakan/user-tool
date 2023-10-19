import typer
import rich
from rich.pretty import pprint
import requests
from fillpdf import fillpdfs
import json
import secrets
import os

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

# Fill out welcome pdf
def fill_welcome_pdf(givenName: str, familyName:str, password: str, gdomain: str, msdomain: str, ggroup: list):
    group_str = ggroup[0][1]
    if len(ggroup) > 1:
        for g in ggroup:
            group_str = f"{group_str}, {g[1]}"

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
    rich.print(f"Username will be {givenname.lower()}.{familyname.lower()}@{gdomain} for {givenname} {familyname}")
    usercorrect = typer.confirm("Is this correct?", default=True)
    if not usercorrect:
        raise typer.Exit(code=1)

    # Get Google Workspaces groups list and print
    groups = get_google_groups()
    for i in range(len(groups)):
        rich.print(f"[{i}] {groups[i]['name']} ({groups[i]['email']})")
    # Prompt for group
    addgroup = typer.prompt("Which group should the user be added to? (Separate multiple groups with comma)")
    # Split groups
    grouplist = addgroup.split(",")
    addgroup = []
    for g in grouplist:
        addgroup.append([groups[int(g)]["email"], groups[int(g)]["name"]])

    # Create user on google workspace
    rich.print(f"☑️ Creating user on Google Workspace")
    try:
        guser = create_google_user(givenname, familyname, password, gdomain)
    except Exception as e:
        rich.print(f"❌ Failed to create user on Google Workspace")
        rich.print(e)
        raise typer.Exit(code=1)

    # Check return
    if guser:
        rich.print(f"✅ User {guser['primaryEmail']} created on Google Workspace")

    # Add user to groups
    for group in addgroup:
        rich.print(f"☑️ Adding user to group {group[1]}")
        try:
            add_to_google_group(group[0], guser["primaryEmail"])
        except Exception as e:
            rich.print(f"❌ Failed to add user to group {group[1]}")
            rich.print(e)
            raise typer.Exit(code=1)
        rich.print(f"✅ User added to group {group[1]}")

    # Get Graph API token
    token = get_graph_token()

    # Create user on AzureAD
    rich.print(f"☑️ Creating user on AzureAD")
    msuser = create_azure_user(token, givenname, familyname, password, msdomain)

    # Check return
    if msuser.status_code == 201:
        rich.print(f"✅ User created on AzureAD")
    elif msuser.status_code == 400 and json.loads(msuser.text)["error"]["message"] == "Another object with the same value for property userPrincipalName already exists.":
        rich.print(f"❌ User already exists on AzureAD")
    else:
        rich.print(f"❌ Failed to create user on AzureAD. Error: {msuser.status_code} {msuser['message']}")
        raise typer.Exit(code=1)
    
    # Fill out welcome pdf
    rich.print(f"☑️ Filling out welcome pdf")
    fill_welcome_pdf(givenname, familyname, password, gdomain, msdomain, addgroup)
    rich.print(f"✅ Welcome pdf filled out")

    rich.print("All done!")

# List groups
@app.command(help = "List groups")
def listgroups():
    groups = get_google_groups()
    for group in groups:
        pprint({"Name": group["name"], "Email": group["email"]}, expand_all=True)


if __name__ == "__main__":
    app()