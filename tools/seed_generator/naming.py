"""Random, category-prefixed names for generated seeds."""

import secrets

from .words import ADJECTIVES, NOUNS


def generate_seed_name(category: str) -> str:
    """Return a random seed name in the form Category-AdjectiveNounNumber."""
    random_name = f"{secrets.choice(ADJECTIVES)}{secrets.choice(NOUNS)}{secrets.randbelow(99) + 1}"
    return f"{category}-{random_name}"
