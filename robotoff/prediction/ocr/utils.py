from typing import Callable, Iterable

from robotoff.utils.text import KeywordProcessor


def generate_keyword_processor(
    items: Iterable[str], keep_func: Callable | None = None
) -> KeywordProcessor:
    processor = KeywordProcessor()

    for item in items:
        splitted = item.split("||")

        if len(splitted) == 2:
            key, name = splitted
            pattern = name
        elif len(splitted) == 3:
            key, name, pattern = splitted
        else:
            raise ValueError("invalid syntax: '{}'".format(item))

        if keep_func is not None and not keep_func(key, name):
            continue

        processor.add_keyword(pattern, clean_name=(key, name))

    return processor
