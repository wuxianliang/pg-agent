"""Range-trio source_line fixture.

Explicit Python source. Not Kohaku markdown, not MinerU content_list,
and not a live parser output.
"""


def greeting() -> str:
    return "range-trio source_line"


if __name__ == "__main__":
    print(greeting())
