"""Dummy seed generator for verifying the bot's command environment."""

import os
from pathlib import Path
from time import sleep

def main() -> None:
    sleep(2)
    print("Seed generator environment variables:")
    tmp =""
    for variable, value in sorted(os.environ.items()):
        if variable.startswith("RACE_"):
            tmp+=f"{variable}={value}"

    seeds_directory = Path(os.environ["RACE_SEEDS_DIRECTORY"])
    output_file = seeds_directory / "dummy-seed.txt"
    output_file.write_text(tmp, encoding="utf-8")
    print(f"Created seed file: {output_file}")


if __name__ == "__main__":
    main()
