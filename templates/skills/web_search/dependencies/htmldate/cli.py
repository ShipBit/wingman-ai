"""
Implementing a basic command-line interface.
"""

import argparse
import logging
import sys

from platform import python_version
from typing import Any, Optional, Union

from lxml.html import HtmlElement

from . import __version__
from .core import find_date
from .utils import fetch_url
from .settings import MIN_FILE_SIZE, MAX_FILE_SIZE


def examine(
    htmlstring: Union[str, HtmlElement],
    extensive_bool: bool = True,
    original_date: bool = False,
    verbose_flag: bool = False,
    mindate: Optional[Any] = None,
    maxdate: Optional[Any] = None,
) -> Optional[str]:
    """Generic safeguards and triggers"""
    # safety check
    if htmlstring is None:
        sys.stderr.write("# ERROR: empty document\n")
    elif len(htmlstring) > MAX_FILE_SIZE:
        sys.stderr.write("# ERROR: file too large\n")
    elif len(htmlstring) < MIN_FILE_SIZE:
        sys.stderr.write("# ERROR: file too small\n")
    else:
        return find_date(
            htmlstring,
            extensive_search=extensive_bool,
            original_date=original_date,
            verbose=verbose_flag,
            min_date=mindate,
            max_date=maxdate,
        )
    return None


def parse_args(args: Any) -> Any:
    """Define parser for command-line arguments"""
    argsparser = argparse.ArgumentParser()
    argsparser.add_argument(
        "-f", "--fast", help="fast mode: disable extensive search", action="store_false"
    )
    argsparser.add_argument(
        "-i",
        "--inputfile",
        help="""name of input file for batch processing
                            (similar to wget -i)""",
        type=str,
    )
    argsparser.add_argument(
        "--original", help="original date prioritized", action="store_true"
    )
    argsparser.add_argument(
        "-min", "--mindate", help="earliest acceptable date (ISO 8601 YMD)", type=str
    )
    argsparser.add_argument(
        "-max", "--maxdate", help="latest acceptable date (ISO 8601 YMD)", type=str
    )
    argsparser.add_argument("-u", "--URL", help="custom URL download", type=str)
    argsparser.add_argument(
        "-v", "--verbose", help="increase output verbosity", action="store_true"
    )
    argsparser.add_argument(
        "--version",
        help="show version information and exit",
        action="version",
        version=f"Htmldate {__version__} - Python {python_version()}",
    )
    return argsparser.parse_args()


def process_args(args: Any) -> None:
    """Process the arguments passed on the command-line."""
    # verbosity
    if args.verbose is True:
        logging.basicConfig(level=logging.DEBUG)

    # input type
    if not args.inputfile:
        # URL as input
        if args.URL:
            htmlstring = fetch_url(args.URL)
            if htmlstring is None:
                sys.exit(f"# ERROR no valid result for url: {args.URL}" + "\n")
        # unicode check
        else:
            try:
                htmlstring = sys.stdin.read()
            except UnicodeDecodeError as err:
                sys.exit(f"# ERROR system/buffer encoding: {str(err)}" + "\n")
        result = examine(
            htmlstring,
            extensive_bool=args.fast,
            original_date=args.original,
            verbose_flag=args.verbose,
            maxdate=args.maxdate,
        )
        if result is not None:
            sys.stdout.write(result + "\n")

    # process input file line by line
    else:
        with open(args.inputfile, mode="r", encoding="utf-8") as inputfile:
            for line in inputfile:
                htmltext = fetch_url(line.strip())
                result = examine(
                    htmltext,  # type: ignore[arg-type]
                    extensive_bool=args.fast,
                    original_date=args.original,
                    verbose_flag=args.verbose,
                    mindate=args.mindate,
                    maxdate=args.maxdate,
                )
                if result is None:
                    result = "None"
                sys.stdout.write(line.strip() + "\t" + result + "\n")


def main() -> None:
    """Run as a command-line utility."""
    # arguments
    args = parse_args(sys.argv[1:])
    # process input on STDIN
    process_args(args)


if __name__ == "__main__":
    main()
