import re
from typing import Union

from openfoodfacts.ocr import (
    OCRField,
    OCRRegex,
    OCRResult,
    get_match_bounding_box,
    get_text,
)

from robotoff.types import JSONType, Prediction, PredictionType

# Increase version ID when introducing breaking change: changes for which we
# want old predictions to be removed in DB and replaced by newer ones
PREDICTOR_VERSION = "1"


NutrientMentionType = tuple[str, list[str]]

NUTRIENT_MENTION: dict[str, list[NutrientMentionType]] = {
    "energy": [
        ("énergie", ["fr"]),
        ("energie", ["fr", "de", "nl"]),
        ("valeurs? [ée]nerg[ée]tiques?", ["fr"]),
        ("energy", ["en"]),
        ("calories", ["fr", "en"]),
        ("energia", ["es", "it", "pt", "hu"]),
        ("valor energ[ée]tico", ["es"]),
        ("energi", ["da"]),
    ],
    "saturated_fat": [
        ("mati[èe]res? grasses? satur[ée]s?", ["fr"]),
        ("acides? gras satur[ée]s?", ["fr"]),
        ("dont satur[ée]s?", ["fr"]),
        ("acidi grassi saturi", ["it"]),
        ("saturated fat", ["en"]),
        ("of which saturates", ["en"]),
        ("verzadigde vetzuren", ["nl"]),
        ("waarvan verzadigde", ["nl"]),
        ("gesättigte fettsäuren", ["de"]),
        ("[aá]cidos grasos saturados", ["es"]),
        ("dos quais saturados", ["pt"]),
        ("mættede fedtsyrer", ["da"]),
        ("amelyb[őö]l? telített zs[íi]rsavak", ["hu"]),
    ],
    "trans_fat": [
        ("mati[èe]res? grasses? trans", ["fr"]),
        ("trans fat", ["en"]),
    ],
    "fat": [
        ("mati[èe]res? grasses?", ["fr"]),
        ("graisses?", ["fr"]),
        ("lipides?", ["fr"]),
        ("total fat", ["en"]),
        ("vetten", ["nl"]),
        ("fett", ["de"]),
        ("grasas", ["es"]),
        ("grassi", ["it"]),
        ("l[íi]pidos", ["es", "pt"]),
        ("fedt", ["da"]),
        ("zs[íi]r", ["hu"]),
    ],
    "sugar": [
        ("sucres?", ["fr"]),
        ("sugars?", ["en"]),
        ("zuccheri", ["it"]),
        ("suikers?", ["nl"]),
        ("zucker", ["de"]),
        ("az[úu]cares", ["es"]),
        ("sukkerarter", ["da"]),
        ("amelyb[őö]l? cukrok", ["hu"]),
    ],
    "carbohydrate": [
        ("total carbohydrate", ["en"]),
        ("glucids?", ["fr"]),
        ("glucides?", ["en"]),
        ("carboidrati", ["it"]),
        ("koolhydraten", ["nl"]),
        ("koolhydraat", ["nl"]),
        ("kohlenhydrate", ["de"]),
        ("hidratos de carbono", ["es", "pt"]),
        ("kulhydrat", ["da"]),
        ("szénhidrát", ["hu"]),
    ],
    "protein": [
        ("prot[ée]ines?", ["fr"]),
        ("protein", ["en", "da"]),
        ("eiwitten", ["nl"]),
        ("eiweiß", ["de"]),
        ("prote[íi]nas", ["es", "pt"]),
        ("fehérje", ["hu"]),
    ],
    "salt": [
        ("sel", ["fr"]),
        ("salt", ["en", "da"]),
        ("zout", ["nl"]),
        ("salz", ["de"]),
        ("sale", ["it"]),
        ("sal", ["es", "pt"]),
        ("só", ["hu"]),
    ],
    "fiber": [
        ("fibres?", ["en", "fr", "it"]),
        ("(?:dietary )?fibers?", ["en"]),
        ("fibres? alimentaires?", ["fr"]),
        ("(?:voedings)?vezels?", ["nl"]),
        ("ballaststoffe", ["de"]),
        ("fibra(?: alimentaria)?", ["es"]),
        ("kostfibre", ["da"]),
        ("rost", ["hu"]),
    ],
    "nutrition_values": [
        ("informations? nutritionnelles?(?: moyennes?)?", ["fr"]),
        ("valeurs? nutritionnelles?(?: moyennes?)?", ["fr"]),
        ("analyse moyenne pour", ["fr"]),
        ("valeurs? nutritives?", ["fr"]),
        ("valeurs? moyennes?", ["fr"]),
        ("nutrition facts?", ["en"]),
        ("average nutritional values?", ["en"]),
        ("valori nutrizionali medi", ["it"]),
        ("gemiddelde waarden per", ["nl"]),
        ("nutritionele informatie", ["nl"]),
        ("(er)?næringsindhold", ["da"]),
        ("átlagos tápérték(?:tartalom)?", ["hu"]),
        ("tápérték adatok", ["hu"]),
    ],
}


NUTRIENT_UNITS: dict[str, list[str]] = {
    "energy": ["kj", "kcal"],
    "saturated_fat": ["g"],
    "trans_fat": ["g"],
    "fat": ["g"],
    "sugar": ["g"],
    "carbohydrate": ["g"],
    "protein": ["g"],
    "salt": ["g", "mg"],
    "fiber": ["g"],
}


def generate_nutrient_regex(
    nutrient_mentions: list[NutrientMentionType], units: list[str]
):
    nutrient_names = [x[0] for x in nutrient_mentions]
    nutrient_names_str = "|".join(nutrient_names)
    units_str = "|".join(units)
    return re.compile(
        r"(?<!\w)({}) ?(?:[:-] ?)?([0-9]+[,.]?[0-9]*) ?({})(?!\w)".format(
            nutrient_names_str, units_str
        ),
        re.I,
    )


def generate_nutrient_mention_regex(nutrient_mentions: list[NutrientMentionType]):
    sub_re = "|".join(
        r"(?P<{}>{})".format("{}_{}".format("_".join(lang), i), name)
        for i, (name, lang) in enumerate(nutrient_mentions)
    )
    return re.compile(r"(?<!\w){}(?!\w)".format(sub_re), re.I)


NUTRIENT_VALUES_REGEX = {
    nutrient: OCRRegex(
        generate_nutrient_regex(NUTRIENT_MENTION[nutrient], units),
        field=OCRField.full_text_contiguous,
    )
    for nutrient, units in NUTRIENT_UNITS.items()
}

NUTRIENT_MENTIONS_REGEX: dict[str, OCRRegex] = {
    nutrient: OCRRegex(
        generate_nutrient_mention_regex(NUTRIENT_MENTION[nutrient]),
        field=OCRField.full_text_contiguous,
    )
    for nutrient in NUTRIENT_MENTION
}
NUTRIENT_MENTIONS_REGEX["nutrient_value"] = OCRRegex(
    re.compile(
        r"(?<!\w)([0-9]+[,.]?[0-9]*) ?(g|kj|kcal)(?!\w)",
        re.I,
    ),
    field=OCRField.full_text_contiguous,
)


def find_nutrient_values(content: Union[OCRResult, str]) -> list[Prediction]:
    nutrients: JSONType = {}

    for regex_code, ocr_regex in NUTRIENT_VALUES_REGEX.items():
        text = get_text(content, ocr_regex)

        if not text:
            continue

        for match in ocr_regex.regex.finditer(text):
            value = match.group(2).replace(",", ".")
            unit = match.group(3)
            nutrients.setdefault(regex_code, [])
            nutrients[regex_code].append(
                {
                    "raw": match.group(0),
                    "nutrient": regex_code,
                    "value": value,
                    "unit": unit,
                }
            )

    if not nutrients:
        return []

    return [
        Prediction(
            type=PredictionType.nutrient,
            data={"nutrients": nutrients},
            predictor_version=PREDICTOR_VERSION,
            predictor="regex",
        )
    ]


def find_nutrient_mentions(content: Union[OCRResult, str]) -> list[Prediction]:
    nutrients: JSONType = {}

    for nutrient_name, ocr_regex in NUTRIENT_MENTIONS_REGEX.items():
        text = get_text(content, ocr_regex)

        if not text:
            continue

        for match in ocr_regex.regex.finditer(text):
            nutrients.setdefault(nutrient_name, [])
            nutrient_data = {
                "raw": match.group(0),
                "span": list(match.span()),
            }

            if nutrient_name != "nutrient_value":
                # Language available for all nutrient fields except
                # 'nutrient_value'
                group_dict = {
                    k: v for k, v in match.groupdict().items() if v is not None
                }
                languages: list[str] = []
                if group_dict:
                    languages_raw = list(group_dict.keys())[0]
                    languages = languages_raw.rsplit("_", maxsplit=1)[0].split("_")

                nutrient_data["languages"] = languages

            if (
                bounding_box := get_match_bounding_box(
                    content, match.start(), match.end()
                )
            ) is not None:
                nutrient_data["bounding_box_absolute"] = bounding_box

            nutrients[nutrient_name].append(nutrient_data)

    if not nutrients:
        return []

    return [
        Prediction(
            type=PredictionType.nutrient_mention,
            data={"mentions": nutrients},
            predictor_version=PREDICTOR_VERSION,
        )
    ]
