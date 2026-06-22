import argparse, hashlib, json, asyncio
import os, shutil, requests
import zipfile, py7zr
from pathlib import Path

def github_headers(token, download=False):
    headers = {
        "Authorization": f"token {token}",
        "User-Agent": "NECTO-release-assets-script"
    }

    if download:
        headers["Accept"] = "application/octet-stream"

    return headers


def get_latest_release(repo, token):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    response = requests.get(url, headers=github_headers(token))
    response.raise_for_status()
    return response.json()


def get_release_assets(repo, release_id, token):
    assets = []
    page = 1

    while True:
        url = f"https://api.github.com/repos/{repo}/releases/{release_id}/assets?page={page}&per_page=100"
        response = requests.get(url, headers=github_headers(token))
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


def write_metadata(output_dir, metadata):
    metadata_path = output_dir / "metadata.json"

    with open(metadata_path, "w") as metadata_file:
        json.dump(
            {
                "dependencies": metadata
            },
            metadata_file,
            indent=4
        )

    return metadata_path


def upload_changed_assets(token, repo, output_dir, metadata):
    latest_release = get_latest_release(repo, token)
    release_id = latest_release["id"]

    print(f"\033[94mLatest release: {latest_release['tag_name']}\033[0m")

    assets = get_release_assets(repo, release_id, token)
    existing_metadata = fetch_release_metadata(assets, token)

    metadata_path = write_metadata(output_dir, metadata)

    if not existing_metadata:
        print("\033[93mmetadata.json does not exist in latest release. Uploading everything.\033[0m")

        for asset_path in sorted(output_dir.iterdir()):
            existing_asset = find_asset(assets, asset_path.name)
            if existing_asset:
                delete_release_asset(existing_asset, token)

            upload_release_asset(repo, release_id, asset_path, token)

        return

    existing_dependencies = existing_metadata.get("dependencies", {})

    changed_assets = []

    for archive_name, archive_metadata in metadata.items():
        existing_archive_metadata = existing_dependencies.get(archive_name)
        existing_asset = find_asset(assets, archive_name)

        if not existing_archive_metadata:
            print(f"\033[93mNew asset detected: {archive_name}\033[0m")
            changed_assets.append(archive_name)
            continue

        if not existing_asset:
            print(f"\033[93mAsset exists in metadata but not in release: {archive_name}\033[0m")
            changed_assets.append(archive_name)
            continue

        if existing_archive_metadata.get("hash") != archive_metadata.get("hash"):
            print(f"\033[93mHash changed: {archive_name}\033[0m")
            changed_assets.append(archive_name)
            continue

        print(f"\033[92mNo changes: {archive_name}\033[0m")

    for archive_name in changed_assets:
        asset_path = output_dir / archive_name
        existing_asset = find_asset(assets, archive_name)

        if existing_asset:
            delete_release_asset(existing_asset, token)

        upload_release_asset(repo, release_id, asset_path, token)

    if changed_assets:
        metadata_asset = find_asset(assets, "metadata.json")
        if metadata_asset:
            delete_release_asset(metadata_asset, token)

        upload_release_asset(repo, release_id, metadata_path, token)
    else:
        print("\033[92mNo changed assets. metadata.json upload skipped.\033[0m")


def iter_files(directory):
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        files.sort()
        for filename in files:
            yield Path(root) / filename


def hash_directory_contents(directory):
    digest = hashlib.sha256()

    for file_path in iter_files(directory):
        relative_path = file_path.relative_to(directory).as_posix()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        with file_path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")

    return digest.hexdigest()


def create_zip_from_contents(source_folder: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in iter_files(source_folder):
            archive.write(file_path, file_path.relative_to(source_folder).as_posix())


def create_7z_from_contents(source_folder: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    with py7zr.SevenZipFile(archive_path, "w") as archive:
        for file_path in iter_files(source_folder):
            archive.write(file_path, file_path.relative_to(source_folder).as_posix())


def package_translation_archives(repo_root, output_dir):
    metadata_dependecies = {}

    for locale in (repo_root / 'necto-translations').iterdir():
        archive_name = f"necto-translations-{locale.name}.zip"
        archive_path = output_dir / archive_name

        print(f"\033[94mCreating translation archive: {archive_name}\033[0m")
        create_zip_from_contents(locale, archive_path)

        # Get the package metadata
        metadata_path = locale / "manifest.json"
        with open(metadata_path, 'r') as translation_metadata_file:
            metadata_dependecies[archive_name] = json.load(translation_metadata_file)
        metadata_dependecies[archive_name]['hash'] = hash_directory_contents(locale)

    return metadata_dependecies


def list_template_folders(templates_root_path):
    folders = []

    if not templates_root_path.is_dir():
        return folders

    for folder in sorted(templates_root_path.iterdir()):
        if folder.name != "project_templates":
            folders.append(folder.name)

    project_templates_root = templates_root_path / "project_templates"
    if project_templates_root.is_dir():
        for folder in sorted(project_templates_root.iterdir()):
            folders.append(f"project_templates/{folder.name}")

    return folders


def package_template_archives(repo_root, output_dir, necto_version):
    metadata_dependecies = {}

    templates_root = repo_root / "templates" / "necto" / necto_version
    for folder in list_template_folders(templates_root):
        folder_path = templates_root / folder
        archive_leaf = folder.replace("project_templates/", "")
        archive_name = f"templates_{necto_version}_{archive_leaf}.7z"
        archive_path = output_dir / archive_name

        print(f"\033[94mCreating template archive: {archive_name}\033[0m")
        create_7z_from_contents(folder_path, archive_path)
        metadata_dependecies[archive_name] = {
            "hash": hash_directory_contents(folder_path),
            "install_location": f"%APPLICATION_DATA_DIR%/templates/{folder}"
            }

    return metadata_dependecies


def package_utility_archives(repo_root, output_dir):
    metadata_dependecies = {}

    for folder in (repo_root / "utils").iterdir():
        archive_name = f"{folder.name}.7z"
        archive_path = output_dir / archive_name
        print(f"\033[94mCreating utility archive: {archive_name}\033[0m")
        create_7z_from_contents(folder, archive_path)
        metadata_dependecies[archive_name] = {"hash": hash_directory_contents(folder)}

    return metadata_dependecies


def ensure_clean_output_dir(repo_root):
    output_dir = repo_root / "tmp" / "release_assets"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


async def main(token, repo, necto_version):
    repo_root = Path(os.getcwd()).resolve()
    # Clean the leftovers from previous runs if running it locally
    output_dir = ensure_clean_output_dir(repo_root)

    print(f"\033[94mRepository root: {repo_root}\033[0m")
    print(f"\033[94mOutput folder:   {output_dir}\033[0m")

    metadata = {}

    # Pack translation packages
    metadata.update(package_translation_archives(repo_root, output_dir))

    # Pack templates packages
    metadata.update(package_template_archives(repo_root, output_dir, necto_version))

    # Pack utils packages
    metadata.update(package_utility_archives(repo_root, output_dir))

    # Save metadata as a file
    with open(output_dir / "metadata.json", 'w') as metadata_file:
        json.dump(metadata, metadata_file, indent=4)

    # Upload assets that have changes or new assets
    upload_changed_assets(token, repo, output_dir, metadata)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Package NECTO assets and upload changed archives to the latest GitHub release."
    )
    parser.add_argument("token", help="GitHub token")
    parser.add_argument("repo", help="Repository name")
    parser.add_argument("necto_version", help="NECTOStudio version (Live, Development or Experimental)")
    args = parser.parse_args()

    asyncio.run(main(args.token, args.repo, args.necto_version))
