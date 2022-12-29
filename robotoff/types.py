import dataclasses
import enum
import uuid
from typing import Any

#: A precise expectation of what mappings looks like in json.
#: (dict where keys are always of type `str`).
JSONType = dict[str, Any]


class WorkerQueue(enum.Enum):
    robotoff_high = "robotoff-high"
    robotoff_low = "robotoff-low"


class ObjectDetectionModel(enum.Enum):
    nutriscore = "nutriscore"
    universal_logo_detector = "universal-logo-detector"
    nutrition_table = "nutrition-table"


@enum.unique
class PredictionType(str, enum.Enum):
    """PredictionType defines the type of the prediction.

    See `InsightType` documentation for further information about each type.
    """

    ingredient_spellcheck = "ingredient_spellcheck"
    packager_code = "packager_code"
    label = "label"
    category = "category"
    image_flag = "image_flag"
    product_weight = "product_weight"
    expiration_date = "expiration_date"
    brand = "brand"
    image_orientation = "image_orientation"
    store = "store"
    nutrient = "nutrient"
    trace = "trace"
    packaging_text = "packaging_text"
    packaging = "packaging"
    location = "location"
    nutrient_mention = "nutrient_mention"
    image_lang = "image_lang"
    nutrition_image = "nutrition_image"
    nutrition_table_structure = "nutrition_table_structure"


@enum.unique
class InsightType(str, enum.Enum):
    """InsightType defines the type of the insight."""

    # The 'ingredient spellcheck' insight corrects the spelling in the given ingredients list.
    # NOTE: this insight currently relies on manual imports - it's possible these insights have
    # not been generated recently.
    ingredient_spellcheck = "ingredient_spellcheck"

    # The 'packager code' insight extracts the packager code using regex from the image OCR.
    # This insight is always applied automatically.
    packager_code = "packager_code"

    # The 'label' insight predicts a label that appears on the product packaging photo.
    #  Several labels are possible:
    #   - Nutriscore label detection.
    #   - Logo detection using the universal logo detector.
    #   - OCR labeling based on text parsing.
    label = "label"

    # The 'category' insight predicts the category of a product.
    # This insight can be generated by 2 different predictors:
    #  1. The Keras ML category classifier.
    #  2. The Elasticsearch category predictor based on product name.
    #
    # NOTE: there also exists a hierachical category classifier, but it hasn't generated any
    # insights since 2019.
    category = "category"

    # The 'image_flag' insight flags inappropriate images based on OCR text.
    # This insight type is never persisted to the Postgres DB and is only used to pass insight information
    # in memory.
    #
    # Currently 3 possible sources of flagged images are possible:
    #  1) "safe_search_annotation" - Google's SafeSearch API detects explicit content on product images.
    #  2) "label_annotation" - a list of hard-coded labels that should be flagged that are found on the image's OCR.
    #  3) Flashtext matches on the image's OCR.
    image_flag = "image_flag"

    # The 'product_weight' insight extracts the product weight from the image OCR.
    # This insight is never applied automatically.
    product_weight = "product_weight"

    # The 'expiration_date' insight extracts the expiration date from the image OCR.
    expiration_date = "expiration_date"

    # The 'brand' insight extracts the product's brand from the image OCR.
    brand = "brand"

    # The 'image_orientation' insight predicts the image orientation of the given image.
    image_orientation = "image_orientation"

    # The 'store' insight detects the store where the given product is sold from the image OCR.
    store = "store"

    # The 'nutrient' insight detects the list of nutrients mentioned in a product, alongside their numeric value from the image OCR.
    nutrient = "nutrient"

    # The 'trace' insight detects traces that are present in the product from the image OCR.
    # NOTE: there are 0 insights of this type in the Postgres DB.
    trace = "trace"

    # (legacy) The 'packaging_text' insight detects the type of packaging based on the image OCR.
    # This type used to be named 'packaging' and has been renamed into `packaging_text`, so that
    # 'packaging' type can be used for detections of detailed packaging information
    # (shape, material,...).
    # This insight used to be applied automatically.
    packaging_text = "packaging_text"

    # The 'packaging' insight detects the type of packaging based on the image OCR.
    # The details about each packaging element (shape, material, recycling) is returned.
    packaging = "packaging"

    # The 'location' insight detects the location of where the product comes from from the image OCR.
    # NOTE: there are 0 insights of this type in the Postgres DB.
    location = "location"

    # The 'nutrient_mention' insight detect mentions of nutrients from the image OCR (without actual values).
    nutrient_mention = "nutrient_mention"

    # The 'image_lang' insight detects which languages are mentioned on the product from the image OCR.
    image_lang = "image_lang"

    # The 'nutrition_image' insight tags images that have nutrition information based on the 'nutrient_mention' insight and the 'image_orientation' insight.
    # NOTE: this insight and the dependant insights has not been generated since 2020.
    nutrition_image = "nutrition_image"

    # The 'nutritional_table_structure' insight detects the nutritional table structure from the image.
    # NOTE: this insight has not been generated since 2020.
    nutrition_table_structure = "nutrition_table_structure"


@enum.unique
class ElasticSearchIndex(str, enum.Enum):
    product = "product"
    logo = "logo"


@dataclasses.dataclass
class ProductInsightImportResult:
    insight_created_ids: list[uuid.UUID]
    insight_updated_ids: list[uuid.UUID]
    insight_deleted_ids: list[uuid.UUID]
    barcode: str
    type: InsightType


@dataclasses.dataclass
class PredictionImportResult:
    created: int
    barcode: str


@dataclasses.dataclass
class InsightImportResult:
    product_insight_import_results: list[
        ProductInsightImportResult
    ] = dataclasses.field(default_factory=list)
    prediction_import_results: list[PredictionImportResult] = dataclasses.field(
        default_factory=list
    )

    def created_predictions_count(self) -> int:
        return sum(x.created for x in self.prediction_import_results)

    def created_insights_count(self) -> int:
        return sum(
            len(x.insight_created_ids) for x in self.product_insight_import_results
        )

    def deleted_insights_count(self) -> int:
        return sum(
            len(x.insight_deleted_ids) for x in self.product_insight_import_results
        )

    def updated_insights_count(self) -> int:
        return sum(
            len(x.insight_updated_ids) for x in self.product_insight_import_results
        )

    def __repr__(self) -> str:
        return (
            f"<InsightImportResult insights: created={self.created_insights_count()}, "
            f"updated={self.updated_insights_count()}, "
            f"deleted={self.deleted_insights_count()}\n"
            f"types: {list(set(result.type.value for result in self.product_insight_import_results))}"
            f" predictions: created: {self.created_predictions_count()}>"
        )
