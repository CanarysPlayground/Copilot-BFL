import requests
import csv
import logging
import time
import os

from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Fetch the personal access token from environment variable
personal_access_token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")

# Validate the personal access token
if not personal_access_token:
    logging.error("GitHub personal access token is missing. Please set the GITHUB_PERSONAL_ACCESS_TOKEN environment variable.")
    raise ValueError("GitHub personal access token is missing. Please set the GITHUB_PERSONAL_ACCESS_TOKEN environment variable.")

# Setup for resilient HTTP requests
session = requests.Session()
retry = Retry(total=5, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry)
session.mount('http://', adapter)
session.mount('https://', adapter)

# Test the token with a simple API call
test_response = session.get(
    "https://api.github.com/user",
    headers={"Authorization": f"Bearer {personal_access_token}", "Accept": "application/vnd.github+json"}
)
if test_response.status_code == 401:
    logging.error(f"Invalid GitHub personal access token: {test_response.text}")
    raise ValueError("Invalid GitHub personal access token. Please check your repository secrets.")
elif test_response.status_code != 200:
    logging.error(f"Failed to validate GitHub personal access token: {test_response.status_code} - {test_response.text}")
    raise ValueError("Failed to validate GitHub personal access token. Please check your repository secrets.")

# Set up logging
logging.basicConfig(filename='debug.log', level=logging.DEBUG)

# Update headers to include team information
headers = ["Organization", "Username", "Email", "Created At", "Last Activity At", "Pending Cancellation Date", "Team Name"]

# Helper function to get all teams and build user-to-teams mapping
def get_user_teams(org_name, session, token):
    user_teams = {}
    teams_url = f"https://api.github.com/orgs/{org_name}/teams"
    headers_local = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    page = 1
    while True:
        paged_teams_url = f"{teams_url}?per_page=100&page={page}"
        teams_response = session.get(paged_teams_url, headers=headers_local)
        if teams_response.status_code != 200:
            break
        teams = teams_response.json()
        if not teams:
            break
        for team in teams:
            team_name = team.get("name", "N/A")
            team_slug = team.get("slug", "").lower()
            if not team_slug:
                continue
            members_url = f"https://api.github.com/orgs/{org_name}/teams/{team_slug}/members"
            members_page = 1
            while True:
                paged_members_url = f"{members_url}?per_page=100&page={members_page}"
                members_response = session.get(paged_members_url, headers=headers_local)
                if members_response.status_code != 200:
                    break
                members = members_response.json()
                if not members:
                    break
                for member in members:
                    login = member.get("login")
                    if login:
                        user_teams.setdefault(login, []).append(team_name)
                members_page += 1
        page += 1
    return user_teams

# Helper function to get user details (including email)
def get_user_details(username, session, token):
    user_url = f"https://api.github.com/users/{username}"
    response = session.get(user_url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    if response.status_code == 200:
        user_data = response.json()
        email = user_data.get("email", "N/A")  # Will be N/A if email is not public
        return email
    else:
        logging.error(f"Failed to fetch details for user {username}: {response.status_code} - {response.text}")
        return "N/A"

# Open the CSV file for writing data
with open('copilot-seat-analysis.csv', 'w', newline='') as file:
    writer = csv.writer(file)
    writer.writerow(headers)

    # Read the organizations from the file
    with open('orgs.csv', 'r') as orgs_file:
        for line in orgs_file:
            org_name = line.strip()
            if not org_name:
                logging.warning("Empty organization name found in orgs.csv. Skipping...")
                continue

            logging.debug(f'Processing organization: {org_name}')
            print(f'Processing organization: {org_name}')

            # Build user-to-teams mapping for the org
            user_teams_map = get_user_teams(org_name, session, personal_access_token)

            # Fetch Copilot seat assignments with pagination
            page = 1
            while True:
                seats_response = session.get(
                    f"https://api.github.com/orgs/{org_name}/copilot/billing/seats?per_page=100&page={page}",
                    headers={"Authorization": f"Bearer {personal_access_token}", "Accept": "application/vnd.github+json"}
                )
                if seats_response.status_code == 200:
                    seats_data = seats_response.json()
                    if "seats" in seats_data and seats_data["seats"]:
                        for seat in seats_data["seats"]:
                            username = seat.get("assignee", {}).get("login", "N/A")
                            email = get_user_details(username, session, personal_access_token)
                            created_at = seat.get("created_at", "N/A")
                            last_activity_at = seat.get("last_activity_at", "N/A")
                            pending_cancellation_date = seat.get("pending_cancellation_date", "N/A")
                            team_names = ", ".join(user_teams_map.get(username, [])) if username in user_teams_map else "null"
                            writer.writerow([org_name, username, email, created_at, last_activity_at, pending_cancellation_date, team_names])
                            logging.debug(f'Wrote seat data for user: {username}, team: {team_names}, email: {email}')
                        page += 1
                    else:
                        break
                else:
                    logging.error(f"Failed to fetch seat information for {org_name}: {seats_response.status_code} - {seats_response.text}")
                    break

            logging.debug('Waiting for 30 seconds before processing the next organization...')
            print('Waiting for 30 seconds before processing the next organization...')
            time.sleep(30)
