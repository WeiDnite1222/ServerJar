#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

sudo install -Dm755 "$SCRIPT_DIR/sarclient" /usr/local/bin/sarclient
sudo install -Dm755 "$SCRIPT_DIR/serverjar" /usr/local/bin/serverjar

echo "Install completed"
echo "sarclient -> /usr/local/bin/sarclient"
echo "serverjar -> /usr/local/bin/serverjar"