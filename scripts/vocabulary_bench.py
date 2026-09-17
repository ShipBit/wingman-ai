#!/usr/bin/env python3
"""How well does the transcript correction do on a real name list?

    python scripts/vocabulary_bench.py locations.txt commodities.txt
    python scripts/vocabulary_bench.py names.txt --pairs heard_correct.csv
    python scripts/vocabulary_bench.py names.txt --sentences transcripts.txt

Name files: one name per line. The script builds the vocabulary from them,
then measures three things:

* Recall on synthetic misspellings: every name is damaged with one or two
  random edits (as a speech model would) and put into a sentence; the
  correction has to bring it back.
* False positives on plain prose: sentences without any of the names must
  come out unchanged.
* Speed per sentence.

`--pairs` takes a CSV of `heard,correct` lines from real transcripts and
reports which the fuzzy rule alone gets, which need the pair, and which
neither gets. `--sentences` takes real transcripts, one per line, and prints
what the correction would change, for eyeballing.
"""

import argparse
import random
import string
import sys
import time
from os import path

sys.path.insert(0, path.dirname(path.dirname(path.abspath(__file__))))

from services.audio.vocabulary import Vocabulary  # noqa: E402

TEMPLATES = [
    "set a course to {}",
    "how far is {} from here",
    "{} please",
    "I want to buy {} at the terminal",
    "land at {} and wait",
    "what is the price of {} today",
]

PROSE = [
    "please open the map and show me the route",
    "how much fuel do we have left in the tank",
    "start the engines and take off when ready",
    "what time is it and how long until we arrive",
    "tell me a joke about pilots and their ships",
    "scan the area for any hostile contacts nearby",
    "set the power to weapons and prepare to fire",
    "I would like to sell all my cargo at the next station",
    "turn left, then park behind the large building",
    "repeat the last message and stop talking after that",
]


def read_names(files: list[str]) -> list[str]:
    names: list[str] = []
    for file in files:
        with open(file, encoding="utf-8") as f:
            names += [line.strip() for line in f if line.strip() and not line.startswith("#")]
    return list(dict.fromkeys(names))


def damage(word: str, rng: random.Random, edits: int) -> str:
    chars = list(word)
    for _ in range(edits):
        if len(chars) < 2:
            break
        op = rng.choice("sdit")
        i = rng.randrange(len(chars))
        if op == "s":
            chars[i] = rng.choice(string.ascii_lowercase)
        elif op == "d":
            del chars[i]
        elif op == "i":
            chars.insert(i, rng.choice(string.ascii_lowercase))
        elif op == "t" and i < len(chars) - 1:
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


def damage_phrase(phrase: str, rng: random.Random) -> str:
    words = phrase.split()
    edits = 1 if len(phrase) <= 6 else 2
    k = rng.randrange(len(words))
    words[k] = damage(words[k], rng, edits)
    return " ".join(words)


def bench_recall(vocab: Vocabulary, names: list[str], rng: random.Random) -> None:
    hits = misses = 0
    missed: list[tuple[str, str]] = []
    for name in names:
        broken = damage_phrase(name.lower(), rng)
        sentence = rng.choice(TEMPLATES).format(broken)
        out = vocab.correct(sentence)
        if name.lower() in out.lower():
            hits += 1
        else:
            misses += 1
            if len(missed) < 15:
                missed.append((broken, name))
    total = hits + misses
    print(f"recall on synthetic misspellings: {hits}/{total} = {hits / total:.1%}")
    for broken, name in missed:
        print(f"  missed: '{broken}' should be '{name}'")


def bench_false_positives(vocab: Vocabulary) -> None:
    changed = 0
    for sentence in PROSE:
        out = vocab.correct(sentence)
        if out != sentence:
            changed += 1
            print(f"  false positive: '{sentence}' -> '{out}'")
    print(f"false positives on {len(PROSE)} plain sentences: {changed}")


def bench_speed(vocab: Vocabulary) -> None:
    sentence = "please set a course to hurstin and dock at port olisa before the cruzader leaves orbit"
    reps = 100
    t = time.perf_counter()
    for _ in range(reps):
        vocab.correct(sentence)
    ms = (time.perf_counter() - t) / reps * 1000
    print(f"speed: {ms:.2f} ms per 16-word sentence with {len(vocab.entries)} entries")


def bench_pairs(names: list[str], pairs_file: str) -> None:
    fuzzy = Vocabulary(names)
    got_fuzzy = need_pair = neither = 0
    with open(pairs_file, encoding="utf-8") as f:
        for line in f:
            if "," not in line:
                continue
            heard, correct = [p.strip() for p in line.split(",", 1)]
            if not heard or not correct:
                continue
            if correct.lower() in fuzzy.correct(heard).lower():
                got_fuzzy += 1
                continue
            paired = Vocabulary(names + [f"{heard}={correct}"])
            if correct.lower() in paired.correct(heard).lower():
                need_pair += 1
                print(f"  needs a pair: '{heard}' -> '{correct}'")
            else:
                neither += 1
                print(f"  not reachable: '{heard}' -> '{correct}'")
    print(f"real pairs: {got_fuzzy} by fuzzy, {need_pair} by pair, {neither} by neither")


def show_sentences(vocab: Vocabulary, file: str) -> None:
    with open(file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out = vocab.correct(line)
            mark = "  " if out == line else "* "
            print(f"{mark}{line}" + (f"\n   -> {out}" if out != line else ""))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("names", nargs="+", help="text files, one name per line")
    parser.add_argument("--pairs", help="CSV of heard,correct from real transcripts")
    parser.add_argument("--sentences", help="real transcripts, one per line")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    names = read_names(args.names)
    vocab = Vocabulary(names)
    print(f"{len(names)} names, {len(vocab.entries)} usable entries")
    rng = random.Random(args.seed)
    bench_recall(vocab, names, rng)
    bench_false_positives(vocab)
    bench_speed(vocab)
    if args.pairs:
        bench_pairs(names, args.pairs)
    if args.sentences:
        show_sentences(vocab, args.sentences)


if __name__ == "__main__":
    main()
