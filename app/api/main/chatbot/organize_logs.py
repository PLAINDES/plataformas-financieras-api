#!/usr/bin/env python3
"""Organiza boa_suffix_errors.txt en archivos:

  • boa_suffix_found.txt   — tickers que se resolvieron con un sufijo
  • boa_not_found.txt      — tickers que no se pudieron resolver
  • boa_suffix_stats.txt   — estadísticas de uso de sufijos vs no usados
"""

import os
import re
import sys
from collections import defaultdict, Counter

LOG_PATH = os.path.join(os.path.dirname(__file__), "boa_suffix_errors.txt")
FOUND_PATH = os.path.join(os.path.dirname(__file__), "boa_suffix_found.txt")
NOT_FOUND_PATH = os.path.join(os.path.dirname(__file__), "boa_not_found.txt")
STATS_PATH = os.path.join(os.path.dirname(__file__), "boa_suffix_stats.txt")

# Leer sufijos desde boa.py
BOA_PATH = os.path.join(os.path.dirname(__file__), "boa.py")
YAHOO_SUFFIXES = []

if os.path.exists(BOA_PATH):
    with open(BOA_PATH) as f:
        content = f.read()
    m = re.search(r"YAHOO_SUFFIXES\s*=\s*\[(.*?)\]", content, re.DOTALL)
    if m:
        YAHOO_SUFFIXES = re.findall(r'"([^"]+)"', m.group(1))

LINE_RE = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\]\s+(?P<ticker>\S+)\s+->\s+(?P<message>.+)$"
)
SUFFIX_RE = re.compile(r"usó sufijo\s+(?P<suffix>\S+)")


def organize():
    if not os.path.exists(LOG_PATH):
        print(f"No se encontró {LOG_PATH}")
        return

    found: dict[str, list[str]] = defaultdict(list)
    not_found: dict[str, list[str]] = defaultdict(list)
    suffix_counter: Counter[str] = Counter()
    used_suffixes: set[str] = set()
    total_found_entries = 0

    with open(LOG_PATH) as f:
        for line in f:
            m = LINE_RE.match(line.strip())
            if not m:
                continue
            ticker = m.group("ticker")
            msg = m.group("message")
            ts = m.group("timestamp")

            if "no se pudo resolver" in msg.lower():
                not_found[ticker].append(ts)
            else:
                sm = SUFFIX_RE.search(msg)
                suffix = sm.group("suffix") if sm else "desconocido"
                used_suffixes.add(suffix)
                suffix_counter[suffix] += 1
                found[ticker].append(f"{ts} -> {msg}")
                total_found_entries += 1

    # Escribir found
    with open(FOUND_PATH, "w") as f:
        f.write(f"Tickers que requirieron sufijo ({len(found)}):\n")
        f.write("=" * 60 + "\n\n")
        for ticker in sorted(found):
            f.write(f"{ticker}\n")
            for entry in found[ticker]:
                f.write(f"  {entry}\n")
            f.write("\n")

    # Escribir not_found
    with open(NOT_FOUND_PATH, "w") as f:
        f.write(f"Tickers NO resueltos ({len(not_found)}):\n")
        f.write("=" * 60 + "\n\n")
        for ticker in sorted(not_found):
            f.write(f"{ticker}\n")
            for ts in not_found[ticker]:
                f.write(f"  [{ts}]\n")
            f.write("\n")

    # Escribir stats
    unused = [s for s in YAHOO_SUFFIXES if s not in used_suffixes]

    with open(STATS_PATH, "w") as f:
        f.write("Estadísticas de uso de sufijos\n")
        f.write("=" * 60 + "\n\n")

        f.write(f"Total entradas en log: {total_found_entries + sum(len(v) for v in not_found.values())}\n")
        f.write(f"Tickers con sufijo:   {len(found)}\n")
        f.write(f"Tickers no resueltos: {len(not_found)}\n\n")

        f.write("Sufijos USADOS:\n")
        f.write("-" * 40 + "\n")
        for suffix, count in suffix_counter.most_common():
            f.write(f"  {suffix:>6s}  → {count} ticker(s)\n")
        f.write(f"\n  Total: {total_found_entries} ocurrencias\n\n")

        f.write("Sufijos NO USADOS:\n")
        f.write("-" * 40 + "\n")
        if unused:
            for suffix in unused:
                f.write(f"  {suffix}\n")
            f.write(f"\n  Total: {len(unused)} sufijos sin uso\n")
        else:
            f.write("  (todos los sufijos fueron usados)\n")

    print(f"✓ {FOUND_PATH} ({len(found)} tickers)")
    print(f"✓ {NOT_FOUND_PATH} ({len(not_found)} tickers)")
    print(f"✓ {STATS_PATH} ({len(used_suffixes)}/{len(YAHOO_SUFFIXES)} sufijos usados)")


if __name__ == "__main__":
    organize()
