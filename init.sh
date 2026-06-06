echo "Checking environment..."
if command -v uv &> /dev/null; then
    echo "uv installed"
else
    echo "uv not installed. Install it via \"dnf install uv\" or \"apt install uv\" !" >&2
    exit 1
fi

uv venv
uv pip install -r requirements.txt