# Steam Similar Game Scanner

A small command-line scraper that walks Steam's "More Like" recommendations and collects similar games. It fetches recommendation pages like
`https://store.steampowered.com/recommended/morelike/app/<APPID>/`, extracts each
`<div class="similar_grid_item">`, and records the game metadata along with the nearest parent `<div>`'s `id` (used to infer category / placement).

This repository contains a script (`steamlike.py`) that:
- Fetches Steam "More Like" pages using `requests`.
- Parses the HTML using BeautifulSoup and extracts `similar_grid_item` entries.
- Determines the nearest parent `<div>`'s `id` for each item and uses it as a category.
- Queues discovered games and continues scanning in BFS/FIFO or random-step mode.

---

## Features

- Collects recommended games starting from a single `appid`.
- Keeps track of depth, category (inferred from parent div id), and appid/href/game name.
- Command-line options for limits, categories to save, random traversal, and verbosity.
- Exports a simple `out.txt` listing of found games when enabled.

---

## Requirements

- Python 3.10+
- A virtual environment (recommended)

This project supports a `requirements.txt` to pin and install dependencies. If a `requirements.txt`
is present in the repository, you don't need to install packages individually — just install the file.

Quick setup — create and activate a virtual environment (recommended)

Windows (PowerShell):

```powershell
# Create a venv in the project root
python -m venv .venv

# Activate the venv for the current PowerShell session
# If you get an execution policy error, the following enables the script for this session only
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& .\.venv\Scripts\Activate.ps1

# Upgrade pip and install pinned requirements (preferred)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

macOS / Linux (bash / zsh):

```bash
# Create and activate a venv
python3 -m venv .venv
source .venv/bin/activate

# Upgrade pip and install pinned requirements (preferred)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If this repository doesn't include a `requirements.txt`, or you prefer to install manually, install the small set of dependencies directly:

```bash
python -m pip install requests beautifulsoup4 tqdm
```

---

## Usage

Basic command:

```powershell
python Steamilar.py <appid>
```

Example (start from appid `1444480`):

```powershell
python steamlike.py 1444480
```

Command-line options (as implemented in `steamlike.py`):

- `-o`, `--output` : Enable output to file. If provided without value, writes to `out.txt`.
- `-m`, `--max-calls` : Maximum number of URL fetch calls (default 50).
- `-g`, `--max-games` : Maximum number of games to retrieve (default 200).
- `-c`, `--categories` : Space-separated list of categories to save. Defaults to `released`, `topselling`, `newreleases`, `freegames`.
- `-r`, `--random` : Walk queue using random step choices instead of FIFO.
- `-v`, `--verbose` : Enable verbose output while scanning.

Full example (save results, scan up to 100 games, verbose):

```powershell
python steamlike.py 1444480 -o -g 100 -v 
```

---

## What the script records

Each discovered `similar_grid_item` is converted into a dictionary with these fields:

- `appid` — numeric Steam app id (if extractable from the href)
- `href` — full URL pointing to the app page
- `game_name` — slug extracted from the URL when possible
- `depth` — how far from the initial game this recommendation was discovered
- `category` — inferred from the nearest parent `<div>`'s `id` (trailing digits stripped)

The `category` is obtained by walking the element's ancestors and returning the first parent `<div>` that has an `id` attribute. This helps infer whether a recommended game came from, e.g., `morelike_results`, `tab-FreeGames`, `demo_games`, etc.

---

## Output

- When `-o` is used the script writes a simple `out.txt` (or the file you pass) containing `game_name` and `href` lines for the games that matched the selected categories.
- When not using `-o`, the script prints results to stdout.

Example printed summary (abbreviated):

```
Found 75 games after 25 URL calls.
The_Farmer_Was_Replaced   https://store.steampowered.com/app/2060160/The_Farmer_Was_Replaced/
SHENZHEN_IO               https://store.steampowered.com/app/504210/SHENZHEN_IO/
Upload_Labs               https://store.steampowered.com/app/3606890/Upload_Labs/
...
```

---

## Notes & best practices

- Be considerate when scraping Steam. Keep `max_calls` reasonable and avoid high-frequency loops.
- The script uses a user-agent header to mimic a browser. If you need more robust scraping or structured Steam data, prefer using Steam's web API where possible.
- The script relies on HTML structure. If Steam changes their markup, selectors (`div.similar_grid_item`) or parent `id` conventions, extraction may need updating.

---

## Contributing

Contributions are welcome!
If you want me to open a PR, tell me which feature to add and I'll try to implement it.

