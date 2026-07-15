import argparse, hashlib, json, asyncio, zipfile, py7zr
import os, shutil, re
import support

from pathlib import Path

def upload_changed_assets(token, repo, output_dir, metadata):
    latest_release = support.get_latest_release(repo, token)
    release_id = latest_release["id"]

    print(f"\n\n\033[94mLatest release: {latest_release['tag_name']}\033[0m")

    assets = support.get_release_assets(repo, release_id, token)
    existing_metadata = support.fetch_release_metadata(assets, token)

    metadata_path = output_dir / "metadata.json"

    if not existing_metadata:
        print("\033[93mmetadata.json does not exist in latest release. Uploading everything.\033[0m")

        for asset_path in sorted(output_dir.iterdir()):
            existing_asset = support.find_asset(assets, asset_path.name)
            if existing_asset:
                support.delete_release_asset(existing_asset, token)

            support.upload_release_asset(repo, release_id, asset_path, token)

        return

    changed_assets = []

    for archive_name, archive_metadata in metadata.items():
        existing_archive_metadata = existing_metadata.get(archive_name)
        existing_asset = support.find_asset(assets, archive_name)

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
        existing_asset = support.find_asset(assets, archive_name)

        if existing_asset:
            support.delete_release_asset(existing_asset, token)

        support.upload_release_asset(repo, release_id, asset_path, token)

    if changed_assets:
        metadata_asset = support.find_asset(assets, "metadata.json")
        if metadata_asset:
            support.delete_release_asset(metadata_asset, token)

        support.upload_release_asset(repo, release_id, metadata_path, token)
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


def handle_lvgl_package(token, manifest):
    # Find latest release of requested repo
    external_repo = manifest['requires_lvgl_processing']['external_package_repo']
    latest_release = support.get_latest_release(external_repo, token)

    # Find all assets of the latest release of requested repo
    assets = support.get_release_assets(external_repo, latest_release['id'], token)

    # Get the asset info from all found assets
    external_asset_name = manifest['requires_lvgl_processing']['external_package_asset']
    external_asset = support.find_asset(assets, external_asset_name)

    # Handle the asset strucure
    os.makedirs('tmp/lvgl_processing', exist_ok=True)
    support.extract_archive_from_url(external_asset['browser_download_url'], os.path.join('tmp/lvgl_processing/lvgl', external_asset_name.replace('.7z', '')))
    shutil.copytree(manifest['source_folder'], 'tmp/lvgl_processing/lvgl/lvgl/templates/lvgl_designer_generated_code')
    shutil.copytree(manifest['requires_lvgl_processing']['extra_project_template_path'], 'tmp/lvgl_processing/lvgl/lvgl/templates/2_lvgl_designer')

    # Fetch the LCGL version and rename folder accordingly
    with open('tmp/lvgl_processing/lvgl/lvgl/lvgl.h', 'r') as file:
        lvgl_content = file.read()
    version_major = re.search(r'#define LVGL_VERSION_MAJOR\s+(\d+)', lvgl_content).group(1)
    version_minor = re.search(r'#define LVGL_VERSION_MINOR\s+(\d+)', lvgl_content).group(1)
    version_patch = re.search(r'#define LVGL_VERSION_PATCH\s+(\d+)', lvgl_content).group(1)
    lvgl_version = f'{version_major}.{version_minor}.{version_patch}'
    lvgl_folder = lvgl_folder = f'lvgl_{lvgl_version.replace('.', '')}'
    os.rename('tmp/lvgl_processing/lvgl/lvgl', f'tmp/lvgl_processing/lvgl/{lvgl_folder}')
    lvgl_folder = manifest['gh_package_name'].replace('.7z', '').replace('{VERSION}', lvgl_version)
    os.rename('tmp/lvgl_processing/lvgl', f'tmp/lvgl_processing/{lvgl_folder}')

    return f'tmp/lvgl_processing/{lvgl_folder}', lvgl_version


def pack_found_packages(token, metadata, output_dir):
    release_assets_dir = output_dir / "release_assets"
    release_assets_dir.mkdir(parents=True, exist_ok=True)

    # Pre-processing metadata to handle LVGL packages
    lvgl_packages = {}
    delete_lvgl_packages = []
    for package_name, manifest in metadata.items():
        if '{VERSION}' not in package_name:
            continue

        print(f"\033[94mPre-processing: {package_name}\033[0m")

        source_folder, lvgl_version = handle_lvgl_package(token, manifest)
        for field in manifest:
            if isinstance(manifest[field], str) and '{VERSION}' in manifest[field]:
                manifest[field] = manifest[field].replace('{VERSION}', lvgl_version)
        manifest['source_folder'] = source_folder
        delete_lvgl_packages.append(package_name)
        package_name = package_name.replace('{VERSION}', lvgl_version)
        del manifest['requires_lvgl_processing']
        lvgl_packages[package_name] = manifest

    for lvgl_package_to_remove in delete_lvgl_packages:
        del metadata[lvgl_package_to_remove]
    metadata.update(lvgl_packages)

    for package_name, manifest in metadata.items():
        source_folder = Path(manifest["source_folder"]).resolve()
        archive_path = release_assets_dir / package_name

        print(f"\033[94mPacking: {package_name}\033[0m")
        print(f"  Source:  {source_folder}")
        print(f"  Archive: {archive_path}")

        package_name_lower = package_name.lower()

        if package_name_lower.endswith(".zip"):
            create_zip_from_contents(source_folder, archive_path)
        elif package_name_lower.endswith(".7z"):
            create_7z_from_contents(source_folder, archive_path)

        metadata[package_name]['hash'] = hash_directory_contents(source_folder)
        del metadata[package_name]['source_folder']

        print(f"\033[92mPacked successfully: {archive_path}\033[0m")


def find_all_manifests(repo_root):
    metadata = {}

    # Find all manifest.json files in the repo
    for manifest_path in repo_root.rglob("manifest.json"):
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)

        package_name = manifest.get("gh_package_name")
        source_folder = manifest_path.parent
        manifest["source_folder"] = str(source_folder)
        metadata[package_name] = manifest

    return metadata


def ensure_clean_output_dir(repo_root):
    output_dir = repo_root / "tmp"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


async def main(token, repo):
    repo_root = Path(os.getcwd()).resolve()
    # Clean the leftovers from previous runs if running it locally
    output_dir = ensure_clean_output_dir(repo_root)

    print(f"\033[94mRepository root: {repo_root}\033[0m")
    print(f"\033[94mOutput folder:   {output_dir}\n\033[0m")

    metadata = find_all_manifests(repo_root)

    pack_found_packages(token, metadata, output_dir)

    # Save metadata as a file
    with open(output_dir / "release_assets" / "metadata.json", 'w') as metadata_file:
        json.dump(metadata, metadata_file, indent=4)

    # Upload assets that have changes or new assets
    upload_changed_assets(token, repo, output_dir / "release_assets", metadata)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Package NECTO assets and upload changed archives to the latest GitHub release."
    )
    parser.add_argument("token", help="GitHub token")
    parser.add_argument("repo", help="Repository name")
    args = parser.parse_args()

    asyncio.run(main(args.token, args.repo))
