#!/bin/bash
# Deploy changes to local Kodi installation
# Usage: ./deploy_local.sh

# Destination directory
DEST_DIR="$HOME/.kodi/addons"

echo "========================================"
echo "Deploying to $DEST_DIR"
echo "========================================"

# Check if destination exists
if [ ! -d "$DEST_DIR" ]; then
    echo "Error: Kodi addons directory not found at $DEST_DIR"
    exit 1
fi

# Copy AIOStreams Plugin
echo "[+] Copying plugin.video.aiostreams..."
rm -rf "$DEST_DIR/plugin.video.aiostreams"
cp -rf "$(pwd)/plugin.video.aiostreams" "$DEST_DIR/"


echo "========================================"
echo "Deployment Complete!"
echo "Please restart Kodi to load the updated add-on."
echo "========================================"
