import requests

def github_headers(token, download=False):
    headers = {
        "Authorization": f"token {token}",
        "User-Agent": "NECTO-release-assets-script"
    }

    if download:
        headers["Accept"] = "application/octet-stream"

    return headers

def get_latest_release(repo, token):
    ''' Fetch the version that is labeled as "latest" '''
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    resp = requests.get(url, github_headers(token), timeout=30)
    resp.raise_for_status()
    latest_release = resp.json()
    return latest_release

def get_release_assets(repo, release_id, token):
    assets = []
    page = 1

    while True:
        url = f"https://api.github.com/repos/{repo}/releases/{release_id}/assets?page={page}&per_page=100"
        response = requests.get(url, github_headers(token))
        response.raise_for_status()

        page_assets = response.json()
        if not page_assets:
            break

        assets.extend(page_assets)
        page += 1

    return assets

def find_asset(assets, asset_name):
    for asset in assets:
        if asset["name"] == asset_name:
            return asset

    return None

def fetch_release_metadata(assets, token):
    metadata_asset = find_asset(assets, "metadata.json")
    if not metadata_asset:
        return None

    response = requests.get(metadata_asset["url"], headers=github_headers(token, download=True))
    response.raise_for_status()

    return response.json()

def delete_release_asset(asset, token):
    print(f"\033[93mDeleting existing asset: {asset['name']}\033[0m")

    response = requests.delete(asset["url"], headers=github_headers(token))
    response.raise_for_status()

    print(f"\033[91mDeleted asset: {asset['name']}\033[0m")

def upload_release_asset(repo, release_id, asset_path, token):
    asset_name = asset_path.name

    if asset_name.endswith(".zip"):
        content_type = "application/zip"
    elif asset_name.endswith(".7z"):
        content_type = "application/x-7z-compressed"
    elif asset_name.endswith(".json"):
        content_type = "application/json"
    else:
        content_type = "application/octet-stream"

    url = f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={asset_name}"

    headers = github_headers(token)
    headers["Content-Type"] = content_type

    print(f"\033[94mUploading asset: {asset_name}\033[0m")

    with open(asset_path, "rb") as file:
        response = requests.post(url, headers=headers, data=file)

    response.raise_for_status()

    print(f"\033[92mUploaded asset: {asset_name}\033[0m")
    return response.json()
