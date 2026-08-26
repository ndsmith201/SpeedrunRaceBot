"""Parser for the Markdown sections used by the Discord race tracker."""

import re
from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True)
class TrackerTemplate:
    body: str
    sections: dict[str, str]

    def section(self, name: str, **values: str) -> str:
        return self.sections[name].format(**values).rstrip("\n")


def load_tracker_template() -> TrackerTemplate:
    source = (
        files("speedrun_race_bot.templates").joinpath("race_tracker.md").read_text(encoding="utf-8")
    )
    sections = dict(
        re.findall(r"<!-- section: (\w+) -->\n(.*?)<!-- endsection -->", source, re.DOTALL)
    )
    body = re.sub(
        r"<!-- section: \w+ -->\n.*?<!-- endsection -->\n*",
        "",
        source,
        flags=re.DOTALL,
    )
    return TrackerTemplate(body, sections)
