if [ ! -d "$DIR" ]; then
    uv venv
fi

echo "Checking environment..."
if command -v nuitka &> /dev/null; then
    echo "Nuitka installed"
else
    echo "Nuitka not installed. Install it via \"uv pip install nuitka\" !" >&2
    exit 1
fi

nuitka --onefile --standalone --output-filename=serverjar main.py --output-filename=serverjar
nuitka --onefile --standalone --output-filename=sarclent client.py --output-filename=sarclient

echo "Done."