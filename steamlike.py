"""Steam Similar Game Scanner - A tool for discovering similar games on Steam."""

from __future__ import annotations
import argparse
import re
import sys
from dataclasses import dataclass
from typing import NamedTuple, Sequence
import random
from tqdm import tqdm
import requests
from bs4 import BeautifulSoup
from bs4.element import Tag


@dataclass
class GameItem:
    """Represents a Steam game with metadata."""

    appid: str | None
    href: str | None
    game_name: str | None
    depth: int
    category: str

    @classmethod
    def from_tag(cls, tag: Tag, depth: int, category: str) -> GameItem:
        """Create a GameItem from a BeautifulSoup Tag.

        Args:
            tag: BeautifulSoup Tag element representing a game item
            depth: Current depth in the search tree
            category: Category/source of this recommendation

        Returns:
            GameItem instance with extracted data
        """
        anchor = tag.find("a")
        href = str(anchor["href"] if anchor and anchor.has_attr("href") else None)
        appid = None
        game_name = None
        if href:
            pattern = r"app/(\d+)/([^/?]+)"
            match = re.search(pattern, href)
            if match:
                appid = match.group(1)
                game_name = match.group(2)
        return cls(
            appid=appid, href=href, game_name=game_name, depth=depth, category=category
        )

    @classmethod
    def initial_game(cls, appid: str) -> GameItem:
        """Create an initial game item to start scanning from.

        Args:
            appid: Steam application ID

        Returns:
            GameItem for the initial game
        """
        return cls(
            appid=appid,
            href=f"https://store.steampowered.com/app/{appid}/",
            game_name="Initial Game",
            depth=0,
            category="initial",
        )

    def has_valid_appid(self) -> bool:
        """Check if this game item has a valid app ID."""
        return self.appid is not None


@dataclass(frozen=True)
class ScanConfig:
    """Configuration for the game scanner."""

    initial_appid: str
    max_calls: int
    max_games: int
    categories: list[str]
    randomstep: bool
    verbose: bool

    def should_use_progress_bar(self) -> bool:
        """Check if progress bar should be used.

        Returns:
            True if progress bar should be displayed
        """
        return not self.verbose


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
            return str(parent["id"])
        parent = parent.parent
    return None


def normalize_category(parent_id: str | None) -> str:
    """Normalize category by removing trailing digits from parent div ID.

    Args:
        parent_id: The parent div ID

    Returns:
        Normalized category string
    """
    if parent_id:
        return re.sub(r"\d+$", "", parent_id)
    return "unknown"


def url_from_id(appid: str) -> str:
    """Generate Steam recommendation URL from app ID.

    Args:
        appid: Steam application ID

    Returns:
        Full URL to the Steam recommendation page
    """
    return f"https://store.steampowered.com/recommended/morelike/app/{appid}/"


class ProgressUpdate(NamedTuple):
    """Data for a progress update."""

    items_scanned: int
    count_added: int
    total_found: int


def display_progress(
    verbose: bool, pbar, update: ProgressUpdate, max_games: int
) -> None:
    """Display progress information.

    Args:
        verbose: If True, use verbose output instead of progress bar
        pbar: Progress bar object or None
        update: Progress update data
        max_games: Maximum number of games for progress calculation
    """
    if verbose:
        print(f"**SCANNED {update.items_scanned} GAMES**")
        print(f"KEPT: {update.count_added}")
        print(f"TOTAL FOUND GAMES: {update.total_found}\n\n")
    elif pbar:
        pbar.update(min(update.count_added, max_games - update.total_found))


class GameScanner:
    """Manages the scanning of Steam similar games."""

    def __init__(self, config: ScanConfig):
        """Initialize the game scanner.

        Args:
            config: Scanner configuration
        """
        self.config = config
        self.queue: list[GameItem] = [GameItem.initial_game(config.initial_appid)]
        self.searched_appids: set[str] = set()
        self.added_appids: set[str] = set()
        self.stored_games: list[GameItem] = []
        self.calls = 0
        self.pbar = None
        if config.should_use_progress_bar():
            self.pbar = tqdm(
                total=config.max_games, desc="Fetching Games", unit="games"
            )

    def _select_next_item(self) -> GameItem:
        """Select next item from queue based on strategy.

        Returns:
            Next GameItem to process
        """
        if self.config.randomstep:
            return random.choice(self.queue)
        return self.queue[0]

    def _reached_call_limit(self) -> bool:
        """Check if call limit has been reached.

        Returns:
            True if call limit reached
        """
        return self.calls >= self.config.max_calls

    def _reached_game_limit(self) -> bool:
        """Check if game limit has been reached.

        Returns:
            True if game limit reached
        """
        return len(self.stored_games) >= self.config.max_games

    def _fetch_similar_games(self, current_item: GameItem) -> list[GameItem]:
        """Fetch similar games for a given game item.

        Args:
            current_item: The game item to fetch recommendations for

        Returns:
            List of discovered similar games

        Raises:
            requests.RequestException: If the HTTP request fails
        """
        url = url_from_id(str(current_item.appid))
        items = fetch_similar_divs(url)
        self.calls += 1

        similar_games = []
        for item in items:
            parent_id = find_parent_div_id(item)
            category = normalize_category(parent_id)
            game_item = GameItem.from_tag(item, current_item.depth + 1, category)

            if self._should_add_game(game_item):
                similar_games.append(game_item)
                self.queue.append(game_item)
                self.added_appids.add(str(game_item.appid))

        return similar_games

    def _should_add_game(self, game: GameItem) -> bool:
        """Check if a game should be added to the queue.

        Args:
            game: GameItem to check

        Returns:
            True if game should be added
        """
        return (
            game.has_valid_appid()
            and game.appid not in self.searched_appids
            and game.appid not in self.added_appids
        )

    def _filter_and_store_games(self, similar_games: list[GameItem]) -> int:
        """Filter games by category and store them.

        Args:
            similar_games: List of discovered games

        Returns:
            Number of games added to storage
        """
        count_added = 0
        for game in similar_games:
            if game.category in self.config.categories:
                self.stored_games.append(game)
                count_added += 1
        return count_added

    def _process_item(self, current_item: GameItem) -> None:
        """Process a single game item from the queue.

        Args:
            current_item: The game item to process
        """
        try:
            similar_games = self._fetch_similar_games(current_item)
            count_added = self._filter_and_store_games(similar_games)
            # Use fetched items count from API response
            items_scanned = len(similar_games) if similar_games else 0
            update = ProgressUpdate(
                items_scanned=items_scanned,
                count_added=count_added,
                total_found=len(self.stored_games),
            )
            display_progress(
                self.config.verbose, self.pbar, update, self.config.max_games
            )
        except requests.RequestException as exc:
            if self.config.verbose:
                print(f"Error fetching URL: {exc}")

        self.searched_appids.add(str(current_item.appid))
        self.queue.remove(current_item)

    def _handle_already_searched(self, current_item: GameItem) -> None:
        """Handle an item that was already searched.

        Args:
            current_item: The item that was already searched
        """
        if self.config.verbose:
            print(f"Already searched appid={current_item.appid}, skipping...\n")
        self.queue.remove(current_item)

    def get_statistics(self) -> dict[str, int]:
        """Get scanning statistics.

        Returns:
            Dictionary with scanning statistics
        """
        return {
            "total_games_found": len(self.stored_games),
            "api_calls_made": self.calls,
            "items_searched": len(self.searched_appids),
            "items_queued": len(self.queue),
        }

    def scan(self) -> tuple[list[GameItem], int, str | None]:
        """Run the scanning process.

        Returns:
            Tuple of (stored_games, api_calls_made, stop_message)
        """
        breakmsg = None

        while self.queue:
            current_item = self._select_next_item()

            # Check stop conditions
            if self._reached_call_limit():
                breakmsg = (
                    f"Reached max calls limit of {self.config.max_calls}. Stopping."
                )
                break

            if self._reached_game_limit():
                breakmsg = (
                    f"Reached max games retrieved limit of "
                    f"{self.config.max_games}. Stopping."
                )
                break

            # Skip if already searched
            if current_item.appid in self.searched_appids:
                self._handle_already_searched(current_item)
                continue

            self._process_item(current_item)

        if self.pbar:
            self.pbar.close()

        # Trim to max games
        if len(self.stored_games) > self.config.max_games:
            self.stored_games = self.stored_games[: self.config.max_games]

        return self.stored_games, self.calls, breakmsg


def write_output(games: list[GameItem], output_file: str) -> None:
    """Write game results to a file.

    Args:
        games: List of game items to write
        output_file: Path to output file
    """
    with open(output_file, "w", encoding="utf-8") as file:
        for game in games:
            file.write(f"{game.game_name}   {game.href}\n")


def print_results(
    games: list[GameItem],
    calls: int,
    breakmsg: str | None,
    output: bool,
    output_file: str | None,
) -> None:
    """Print scan results to console and optionally to file.

    Args:
        games: List of discovered games
        calls: Number of API calls made
        breakmsg: Optional message explaining why scan stopped
        output: Whether to write results to a file
        output_file: Path to output file (if output is True)
    """
    print("\n\n\n\n")
    if breakmsg:
        print(breakmsg)
    print(f"Found {len(games)} games after {calls} URL calls.\n")

    if output and output_file:
        write_output(games, output_file)
        print(f"Written found games to {output_file}")
    else:
        for game in games:
            print(f"{game.game_name}   {game.href}")


def parse_output_args(output_arg) -> tuple[bool, str | None]:
    """Parse output argument into output flag and file path.

    Args:
        output_arg: The output argument from argparse

    Returns:
        Tuple of (output_enabled, output_file_path)
    """
    if output_arg is False:
        return False, None
    if output_arg is True:
        return True, "out.txt"
    return True, output_arg


def run_scanner(config: ScanConfig, output: bool, output_file: str | None) -> None:
    """Run the game scanner with given configuration.

    Args:
        config: Scanner configuration
        output: Whether to write results to a file
        output_file: Path to output file (if output is True)
    """
    scanner = GameScanner(config)
    games, calls, breakmsg = scanner.scan()
    print_results(games, calls, breakmsg, output, output_file)


def main() -> None:
    """Parse command-line arguments and run the Steam game scanner."""
    if len(sys.argv) == 1:
        appid = input("Enter the initial Steam appid to start scanning from: ").strip()
        config = ScanConfig(
            initial_appid=appid,
            max_calls=50,
            max_games=200,
            categories=["released", "topselling", "newreleases", "freegames"],
            randomstep=False,
            verbose=False,
        )
        output = True
        output_file = "out.txt"
    else:
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

        # Parse arguments
        output, output_file = parse_output_args(args.output)
        categories = (
            args.categories
            if args.categories
            else ["released", "topselling", "newreleases", "freegames"]
        )

        # Create configuration
        config = ScanConfig(
            initial_appid=args.appid,
            max_calls=args.max_calls,
            max_games=args.max_games,
            categories=categories,
            randomstep=args.random,
            verbose=args.verbose,
        )

    run_scanner(config, output, output_file)
    if len(sys.argv) == 1:
        input("\n\nPress Enter to exit...")


if __name__ == "__main__":
    main()
