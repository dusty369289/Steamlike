"""Steam Similar Game Scanner - A tool for discovering similar games on Steam."""

from __future__ import annotations
import argparse
import re
import sys
from typing import Sequence
import random
from tqdm import tqdm
import requests
from bs4 import BeautifulSoup
from bs4.element import Tag


def fetch_similar_divs(
    url: str, timeout: int = 10, parser: str = "html.parser"
) -> Sequence[Tag]:
    """Fetch and parse Steam recommendation page, returning similar game items.

    Args:
        url: URL of the Steam recommendation page
        timeout: Request timeout in seconds
        parser: BeautifulSoup parser to use

    Returns:
        Sequence of Tag elements with class 'similar_grid_item'

    Raises:
        requests.RequestException: If the HTTP request fails
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/115.0 Safari/537.36"
        )
    }

    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, parser)
    items = soup.find_all("div", class_="similar_grid_item")
    return items


def find_parent_div_id(tag: Tag) -> str | None:
    """Find the nearest parent div with an id attribute.

    Args:
        tag: BeautifulSoup Tag element to search from

    Returns:
        The id attribute of the nearest parent div, or None if not found
    """
    parent = tag.parent
    while parent is not None and getattr(parent, "name", None):
        if parent.name.lower() == "div" and parent.has_attr("id"):
            return parent["id"]
        parent = parent.parent
    return None


def item_worth_saving(item: Tag) -> bool:
    """Check if a game item contains valid app ID information.

    Args:
        item: BeautifulSoup Tag element representing a game item

    Returns:
        True if the item has a valid Steam app ID, False otherwise
    """
    a = item.find("a")
    href = a["href"] if a and a.has_attr("href") else None
    if href:
        m = re.search(r"/app/(\d+)", href)
        if m:
            return True
    return False


def dictionise_item(item: Tag, depth: int, category: str) -> dict:
    """Convert a game item tag into a dictionary with game metadata.

    Args:
        item: BeautifulSoup Tag element representing a game item
        depth: Current depth in the search tree
        category: Category/source of this recommendation

    Returns:
        Dictionary containing appid, href, game_name, depth, and category
    """
    a = item.find("a")
    href = a["href"] if a and a.has_attr("href") else None
    appid = None
    game_name = None
    if href:
        pattern = r"app/(\d+)/([^/?]+)"
        m = re.search(pattern, href)
        if m:
            appid = m.group(1)
            game_name = m.group(2)
    idict = {
        "appid": appid,
        "href": href,
        "game_name": game_name,
        "depth": depth,
        "category": category,
    }
    return idict


def url_from_id(appid: str) -> str:
    """Generate Steam recommendation URL from app ID.

    Args:
        appid: Steam application ID

    Returns:
        Full URL to the Steam recommendation page
    """
    return f"https://store.steampowered.com/recommended/morelike/app/{appid}/"


def run(
    appid: str,
    output: bool,
    output_file: str | None,
    max_calls: int,
    max_games_retrieved: int,
    categories: list[str],
    randomstep: bool,
    verbose: bool,
) -> None:
    """Run the Steam similar game scanner.

    Performs a breadth-first or random search through Steam's recommendation graph,
    collecting games that match the specified categories.

    Args:
        appid: Initial Steam app ID to start scanning from
        output: Whether to write results to a file
        output_file: Path to output file (if output is True)
        max_calls: Maximum number of HTTP requests to make
        max_games_retrieved: Maximum number of games to collect
        categories: List of categories to filter and save
        randomstep: If True, randomly select from queue instead of FIFO
        verbose: If True, print detailed progress information
    """
    init_item = {
        "appid": appid,
        "href": f"https://store.steampowered.com/app/{appid}/",
        "game_name": "Initial Game",
        "depth": 0,
        "category": "initial",
    }
    itemqueue = [init_item]
    calls = 0
    searched_appids = set()
    added_appids = set()
    stored_games = []
    saved_categories = categories
    pbar = None
    if not verbose:
        pbar = tqdm(total=max_games_retrieved, desc="Fetching Games", unit="games")
    breakmsg = None
    while itemqueue:
        if randomstep:
            current_item = random.choice(itemqueue)
        else:
            current_item = itemqueue[0]
        if calls >= max_calls:
            breakmsg = f"Reached max calls limit of {max_calls}. Stopping."
            break
        if current_item["appid"] in searched_appids:
            if verbose:
                print(f"Already searched appid={current_item['appid']}, skipping...\n")
            itemqueue.remove(current_item)
            continue
        cur_depth = current_item["depth"]

        url = url_from_id(current_item["appid"])
        try:
            items = fetch_similar_divs(url)
            calls += 1
        except requests.RequestException as exc:
            if verbose:
                print(f"Error fetching URL {url}: {exc}")
            itemqueue.remove(current_item)
            continue

        similar_games = []
        for item in items:
            parent_id = find_parent_div_id(item)
            if parent_id:
                parent_id = re.sub(r"\d+$", "", parent_id)
            if item_worth_saving(item):
                idict = dictionise_item(item, cur_depth + 1, parent_id or "unknown")
                if (
                    idict["appid"] not in searched_appids
                    and idict["appid"] not in added_appids
                ):
                    similar_games.append(idict)
                    itemqueue.append(idict)
                    added_appids.add(idict["appid"])

        count_added = 0
        # Store the found similar games
        for game in similar_games:
            if game["category"] in saved_categories:
                stored_games.append(game)
                count_added += 1
        if verbose:
            print(f"**SCANNED {len(items)} GAMES**")
            print(f"KEPT: {count_added}")
            print(f"TOTAL FOUND GAMES: {len(stored_games)}\n\n")
        elif pbar is not None:
            pbar.update(min(count_added, max_games_retrieved - len(stored_games)))
        searched_appids.add(current_item["appid"])

        itemqueue.remove(current_item)

        if len(stored_games) >= max_games_retrieved:
            breakmsg = (
                f"Reached max games retrieved limit of {max_games_retrieved}. Stopping."
            )
            stored_games = stored_games[:max_games_retrieved]
            break
    if pbar is not None:
        pbar.close()
    print("\n\n\n\n")
    if breakmsg:
        print(breakmsg)
    print(f"Found {len(stored_games)} games after {calls} URL calls.\n")
    if output:
        with open(output_file, "w", encoding="utf-8") as f:
            for game in stored_games:
                f.write(f"{game['game_name']}   {game['href']}\n")
        print(f"Written found games to {output_file}")
    else:
        for game in stored_games:
            print(f"{game['game_name']}   {game['href']}")


def main() -> None:
    """Parse command-line arguments and run the Steam game scanner."""
    parser = argparse.ArgumentParser(description="Steam Similar Game Scanner")
    parser.add_argument(
        "-o",
        "--output",
        nargs="?",
        const=True,
        default=False,
        help="Enable output, optionally specifying a destination (default out.txt)",
    )
    parser.add_argument(
        "-m",
        "--max-calls",
        type=int,
        default=50,
        help="Maximum number of URL fetch calls to make (default 50)",
    )
    parser.add_argument(
        "-g",
        "--max-games",
        type=int,
        default=200,
        help="Maximum number of games to retrieve (default 200)",
    )
    parser.add_argument(
        "-c",
        "--categories",
        nargs="+",
        help="Categories to save (default: released topselling newreleases freegames)",
    )
    parser.add_argument(
        "-r",
        "--random",
        action="store_true",
        help=(
            "Will randomly step the queue instead of FIFO "
            "(Can lead to less similar results)"
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output when scanning games",
    )
    parser.add_argument(
        "appid", type=str, help="The initial Steam appid to start scanning from"
    )
    args = parser.parse_args()
    if args.output is False:
        output = False
        output_file = None
    elif args.output is True:
        output = True
        output_file = "out.txt"
    else:
        output = True
        output_file = args.output
    if args.categories is None:
        categories = ["released", "topselling", "newreleases", "freegames"]
    else:
        categories = args.categories
    randomstep = args.random
    verbose = args.verbose
    if not args.appid:
        print("Error: No appid provided.")
        sys.exit(1)

    run(
        args.appid,
        output,
        output_file,
        args.max_calls,
        args.max_games,
        categories,
        randomstep,
        verbose,
    )


if __name__ == "__main__":
    main()
