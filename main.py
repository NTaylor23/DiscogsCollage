from argparse import ArgumentParser, BooleanOptionalAction
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from json import loads
from math import ceil, sqrt
from multiprocessing import cpu_count
from os import getenv
from requests import ConnectionError, get
from typing import List

from PIL import Image


THREADS = cpu_count()
TOKEN = getenv("DISCOGS_TOKEN", None)
if not TOKEN:
    raise EnvironmentError("No Discogs auth token available! Exiting.")

HEADERS = {"Authorization": TOKEN, "User-Agent": "InsomniaDiscogs/1.0"}


def fetch(url: str) -> bytes:
    try:
        response = get(url=url, headers=HEADERS)
        return response.content
    except ConnectionError:
        raise ("Error fetching from image URL.")


class DiscogsCollage:
    """Generate a collage of album art from a user's Discogs collection."""

    def __init__(self, username: str, square_size: int, sort: bool) -> None:
        self.username = username
        self.square_size = square_size
        self.sort = sort

    def create_collage(self, image_bytes: List[bytes]) -> Image:
        """Create a collage on a blank canvas from all album art images. Overflow vertically."""
        sz, idx, trim = len(image_bytes), 0, 0
        dim = ceil(sqrt(sz)) * self.square_size
        images_in_row_col = dim // self.square_size
        if images_in_row_col**2 > (sz + images_in_row_col):
            trim = self.square_size

        result = Image.new(mode="RGB", size=(dim, dim - trim))
        for i in range(0, dim, self.square_size):
            for j in range(0, dim, self.square_size):
                if idx >= sz:
                    return result
                img = Image.open(BytesIO(image_bytes[idx]))
                result.paste(
                    im=img.resize(size=(self.square_size, self.square_size)),
                    box=(j, i, j + self.square_size, i + self.square_size),
                )
                idx += 1

        return result

    def get_images(self, release_thumbnails: List[int]) -> List[bytes]:
        """Retrieve images from URLs, save as bytes."""
        result = []
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            result = list(executor.map(fetch, release_thumbnails))
        return result

    def get_image_urls(self) -> List[str]:
        """Extract image URLs from the user's main collection (0)."""
        release_thumbnails = []
        url = f"https://api.discogs.com/users/{self.username}/collection/folders/0/releases"
        params = {"sort": "artist", "sort-order": "desc"} if self.sort else {}
        try:
            while True:
                response = get(url=url, headers=HEADERS, params=params)
                if response.status_code != 200:
                    raise ConnectionError(
                        f"Discogs API responded with status code {response.status_code}"
                    )
                data = loads(response.text)
                release_thumbnails += list(
                    map(
                        lambda x: x["basic_information"]["cover_image"],
                        data["releases"],
                    )
                )
                pagination = data["pagination"]["urls"]
                if not pagination.get("next", None):
                    break
                url = pagination["next"]

            if not release_thumbnails:
                raise ValueError(
                    (
                        "No images supplied from Discogs API. "
                        "This may be due to an internal error, or you may have no items in your collection."
                    )
                )
            return release_thumbnails
        except (ConnectionError, ValueError) as err:
            raise RuntimeError(f"Could not collect release images:\n{err}")


def validate_user(username: str) -> bool:
    """Ensure the user exists on Discogs"""
    response = get(f"https://api.discogs.com/users/{username}", headers=HEADERS)
    return response.status_code == 200


if __name__ == "__main__":
    parser = ArgumentParser(
        prog="Discogs Collage",
        description="Generate a collage of album art from your Discogs collection",
    )
    parser.add_argument(
        "-u",
        "--username",
        required=True,
        help="The Discogs username to create a collage from.",
    )
    parser.add_argument(
        "-sz",
        "--square-size",
        type=int,
        default=200,
        help="The size of each square in the collage. Default is 200px.",
    )
    parser.add_argument(
        "-so",
        "--sort",
        action=BooleanOptionalAction,
        default=False,
        help="Sort by artist in ascending order. Default is false.",
    )
    args = parser.parse_args()

    if not validate_user(args.username):
        raise ValueError(f"No such user exists: {args.username}")

    collage = DiscogsCollage(args.username, args.square_size, args.sort)

    release_ids = collage.get_image_urls()
    image_bytes = collage.get_images(release_ids)
    result = collage.create_collage(image_bytes)

    result.save(".out.png")  # output to the project folder
