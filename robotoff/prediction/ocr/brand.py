import functools
from typing import Iterable, Union

from openfoodfacts.ocr import OCRResult, get_match_bounding_box, get_text

from robotoff import settings
from robotoff.brands import get_brand_blacklist, keep_brand_from_taxonomy
from robotoff.types import JSONType, Prediction, PredictionType
from robotoff.utils import get_logger, text_file_iter
from robotoff.utils.cache import function_cache_register
from robotoff.utils.text import KeywordProcessor, get_tag

from .utils import generate_keyword_processor

logger = get_logger(__name__)


# Increase version ID when introducing breaking change: changes for which we
# want old predictions to be removed in DB and replaced by newer ones
PREDICTOR_VERSION = "1"


def generate_brand_keyword_processor(
    brands: Iterable[str],
    blacklist: bool = True,
):
    blacklisted_brands: set[str] | None = None
    if blacklist:
        blacklisted_brands = get_brand_blacklist()

    keep_func = functools.partial(
        keep_brand_from_taxonomy,
        blacklisted_brands=blacklisted_brands,
    )
    return generate_keyword_processor(brands, keep_func=keep_func)


@functools.cache
def get_logo_annotation_brands() -> dict[str, str]:
    brands: dict[str, str] = {}

    for item in text_file_iter(settings.OCR_LOGO_ANNOTATION_BRANDS_DATA_PATH):
        if "||" in item:
            logo_description, label_tag = item.split("||")
        else:
            logger.warning("'||' separator expected!")
            continue

        brands[logo_description] = label_tag

    return brands


@functools.cache
def get_taxonomy_brand_processor():
    return generate_brand_keyword_processor(
        text_file_iter(settings.OCR_TAXONOMY_BRANDS_PATH)
    )


@functools.cache
def get_brand_processor():
    return generate_brand_keyword_processor(
        text_file_iter(settings.OCR_BRANDS_PATH),
    )


def extract_brands(
    processor: KeywordProcessor,
    content: Union[OCRResult, str],
    data_source_name: str,
    automatic_processing: bool,
) -> list[Prediction]:
    predictions = []

    text = get_text(content)
    for (brand_tag, brand), span_start, span_end in processor.extract_keywords(
        text, span_info=True
    ):
        match_str = text[span_start:span_end]
        data: JSONType = {"text": match_str}
        if (
            bounding_box := get_match_bounding_box(content, span_start, span_end)
        ) is not None:
            data["bounding_box_absolute"] = bounding_box

        predictions.append(
            Prediction(
                type=PredictionType.brand,
                value=brand,
                value_tag=brand_tag,
                automatic_processing=automatic_processing,
                predictor=data_source_name,
                data=data,
                predictor_version=PREDICTOR_VERSION,
            )
        )

    return predictions


def extract_brands_google_cloud_vision(ocr_result: OCRResult) -> list[Prediction]:
    predictions = []
    logo_annotation_brands = get_logo_annotation_brands()
    for logo_annotation in ocr_result.logo_annotations:
        if logo_annotation.description in logo_annotation_brands:
            brand = logo_annotation_brands[logo_annotation.description]

            predictions.append(
                Prediction(
                    type=PredictionType.brand,
                    value=brand,
                    value_tag=get_tag(brand),
                    automatic_processing=False,
                    predictor="google-cloud-vision",
                    confidence=logo_annotation.score,
                    predictor_version=PREDICTOR_VERSION,
                )
            )

    return predictions


def find_brands(content: Union[OCRResult, str]) -> list[Prediction]:
    predictions: list[Prediction] = []

    predictions += extract_brands(
        get_brand_processor(), content, "curated-list", automatic_processing=True
    )
    predictions += extract_brands(
        get_taxonomy_brand_processor(), content, "taxonomy", automatic_processing=False
    )

    if isinstance(content, OCRResult):
        predictions += extract_brands_google_cloud_vision(content)

    return predictions


function_cache_register.register(get_logo_annotation_brands)
function_cache_register.register(get_taxonomy_brand_processor)
function_cache_register.register(get_brand_processor)
