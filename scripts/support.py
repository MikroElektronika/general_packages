import os, re, io, json, requests, sqlite3
from packaging.version import Version

class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def get_latest_release(repo, api_headers):
    ''' Fetch the version that is labeled as "latest" '''
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    resp = requests.get(url, headers=api_headers, timeout=30)
    resp.raise_for_status()
    latest_release = resp.json()
    return latest_release
