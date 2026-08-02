#!/usr/bin/env bash
# Build the GitHub Pages Kodi repository for the current AIOStreams release.

set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADDON_ID="plugin.video.aiostreams"
REPOSITORY_ID="repository.aiostreams"
PAGES_DIR="$BASE_DIR/docs"
DOCUMENTATION="$PAGES_DIR/PLUGIN_DOCUMENTATION.md"
LANDING_PAGE="$PAGES_DIR/index.html"
DOCUMENTATION_RENDERER="$BASE_DIR/scripts/render_documentation.py"
REPOSITORY_DIR="$PAGES_DIR/$REPOSITORY_ID"
ZIPS_DIR="$REPOSITORY_DIR/zips"
ADDON_XML="$BASE_DIR/$ADDON_ID/addon.xml"
REPOSITORY_XML="$REPOSITORY_DIR/addon.xml"

version_from() {
    sed -n 's/.*<addon .*version="\([^"]*\)".*/\1/p' "$1" | head -n 1
}

write_md5() {
    md5sum "$1" | awk '{print $1}' > "$1.md5"
}

verify_md5() {
    local expected actual
    expected="$(<"$1.md5")"
    actual="$(md5sum "$1" | awk '{print $1}')"
    [[ "$actual" == "$expected" ]]
}

build_zip() {
    local destination="$1"
    local directory_name="$2"
    local source_dir="$3"
    local temp_dir
    temp_dir="$(mktemp -d)"

    mkdir -p "$temp_dir/$directory_name"
    rsync -a --delete \
        --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' --exclude='.git*' \
        "$source_dir/" "$temp_dir/$directory_name/"
    (cd "$temp_dir" && zip -r -q "$destination" "$directory_name")
    rm -rf "$temp_dir"
}

build_repository_zip() {
    local destination="$1"
    local temp_dir
    temp_dir="$(mktemp -d)"

    mkdir -p "$temp_dir/$REPOSITORY_ID"
    cp "$REPOSITORY_XML" "$temp_dir/$REPOSITORY_ID/addon.xml"
    cp "$REPOSITORY_DIR/icon.png" "$temp_dir/$REPOSITORY_ID/icon.png"
    (cd "$temp_dir" && zip -r -q "$destination" "$REPOSITORY_ID")
    rm -rf "$temp_dir"
}

addon_version="$(version_from "$ADDON_XML")"
repository_version="$(version_from "$REPOSITORY_XML")"

if [[ -z "$addon_version" || -z "$repository_version" ]]; then
    echo 'Could not determine an add-on or repository version.' >&2
    exit 1
fi

rm -rf "$ZIPS_DIR/$ADDON_ID" "$ZIPS_DIR/$REPOSITORY_ID"
rm -f "$PAGES_DIR/$REPOSITORY_ID-"*.zip "$PAGES_DIR/$REPOSITORY_ID-"*.zip.md5
mkdir -p "$ZIPS_DIR/$ADDON_ID" "$ZIPS_DIR/$REPOSITORY_ID"

addon_zip="$ZIPS_DIR/$ADDON_ID/$ADDON_ID-$addon_version.zip"
build_zip "$addon_zip" "$ADDON_ID" "$BASE_DIR/$ADDON_ID"
write_md5 "$addon_zip"
cp "$ADDON_XML" "$ZIPS_DIR/$ADDON_ID/addon.xml"
cp "$BASE_DIR/$ADDON_ID/resources/icon.png" "$ZIPS_DIR/$ADDON_ID/icon.png"
cp "$BASE_DIR/$ADDON_ID/resources/fanart.jpg" "$ZIPS_DIR/$ADDON_ID/fanart.jpg"

repository_zip="$PAGES_DIR/$REPOSITORY_ID-$repository_version.zip"
build_repository_zip "$repository_zip"
write_md5 "$repository_zip"
cp "$repository_zip" "$ZIPS_DIR/$REPOSITORY_ID/$REPOSITORY_ID-$repository_version.zip"
write_md5 "$ZIPS_DIR/$REPOSITORY_ID/$REPOSITORY_ID-$repository_version.zip"

{
    printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' '<addons>'
    sed -n '/<addon/,/<\/addon>/p' "$REPOSITORY_XML"
    printf '\n'
    sed -n '/<addon/,/<\/addon>/p' "$ADDON_XML"
    printf '%s\n' '</addons>'
} > "$ZIPS_DIR/addons.xml"
write_md5 "$ZIPS_DIR/addons.xml"

python3 -c 'from pathlib import Path; import xml.etree.ElementTree as ET; [ET.parse(path) for path in (Path("docs/repository.aiostreams/addon.xml"), Path("docs/repository.aiostreams/zips/addons.xml"), Path("plugin.video.aiostreams/addon.xml"))]'
unzip -tqq "$addon_zip"
unzip -tqq "$repository_zip"
verify_md5 "$addon_zip"
verify_md5 "$repository_zip"
verify_md5 "$ZIPS_DIR/$REPOSITORY_ID/$REPOSITORY_ID-$repository_version.zip"
verify_md5 "$ZIPS_DIR/addons.xml"
python3 "$DOCUMENTATION_RENDERER" "$DOCUMENTATION" "$LANDING_PAGE" \
    --repository-zip "$REPOSITORY_ID-$repository_version.zip"

echo "Built $ADDON_ID $addon_version and $REPOSITORY_ID $repository_version."
