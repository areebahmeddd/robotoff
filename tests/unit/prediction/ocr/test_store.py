import re

from robotoff import settings
from robotoff.utils import text_file_iter


def test_check_ocr_stores() -> None:
    stores: set[str] = set()
    items: set[str] = set()

    for item in text_file_iter(settings.OCR_STORES_DATA_PATH):
        assert item not in items
        items.add(item)

        assert "’" not in item
        if "||" in item:
            store, regex_str = item.split("||")
        else:
            store = item
            regex_str = re.escape(item.lower())

        re.compile(regex_str)
        stores.add(store)
