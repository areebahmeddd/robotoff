from unittest.mock import Mock

import pytest
from openfoodfacts.types import JSONType

from robotoff.insights.annotate import (
    MISSING_PRODUCT_RESULT,
    OUTDATED_DATA_RESULT,
    UPDATED_ANNOTATION_RESULT,
    AnnotationResult,
    CategoryAnnotator,
    ImageOrientationAnnotator,
    IngredientSpellcheckAnnotator,
    NutrientExtractionAnnotator,
)
from robotoff.models import ProductInsight
from robotoff.off import generate_image_path
from robotoff.types import (
    ObjectDetectionModel,
    PredictionType,
    ProductIdentifier,
    ServerType,
)

from ..models_utils import (
    ImageModelFactory,
    ImagePredictionFactory,
    PredictionFactory,
    ProductInsightFactory,
    clean_db,
)


@pytest.fixture(autouse=True)
def _set_up_and_tear_down(peewee_db):
    with peewee_db:
        # clean db
        clean_db()
        # Run the test case.
        yield
        clean_db()


def test_annotation_fails_is_rolledback(mocker):
    annotator = CategoryAnnotator  # should be enough to test with one annotator

    # make it raise
    mocked = mocker.patch.object(
        annotator, "process_annotation", side_effect=Exception("Blah")
    )
    insight = ProductInsightFactory()
    with pytest.raises(Exception):
        annotator().annotate(insight=insight, annotation=1)
    insight = ProductInsight.get(id=insight.id)
    # unchanged
    assert insight.completed_at is None
    assert insight.annotation is None
    # while process_annotation was called
    assert mocked.called


class TestCategoryAnnotator:
    def test_process_annotation(self, mocker):
        insight = ProductInsightFactory(type="category", value_tag="en:cookies")
        add_category_mocked = mocker.patch("robotoff.insights.annotate.add_category")
        get_product_mocked = mocker.patch(
            "robotoff.insights.annotate.get_product", return_value={}
        )
        result = CategoryAnnotator.process_annotation(insight, is_vote=False)
        add_category_mocked.assert_called_once()
        get_product_mocked.assert_called_once()
        assert result == AnnotationResult(
            status_code=2,
            status="updated",
            description="the annotation was saved and sent to OFF",
        )

    def test_process_annotation_with_user_input_data(self, mocker):
        original_value_tag = "en:cookies"
        insight = ProductInsightFactory(
            type="category", value_tag=original_value_tag, data={}
        )
        user_data = {"value_tag": "en:cookie-dough"}
        add_category_mocked = mocker.patch("robotoff.insights.annotate.add_category")
        get_product_mocked = mocker.patch(
            "robotoff.insights.annotate.get_product", return_value={}
        )
        result = CategoryAnnotator.process_annotation(insight, user_data, is_vote=False)
        add_category_mocked.assert_called_once()
        get_product_mocked.assert_called_once()
        assert result == AnnotationResult(
            status_code=12,
            status="user_input_updated",
            description="the data provided by the user was saved and sent to OFF",
        )
        assert insight.value_tag == user_data["value_tag"]
        assert insight.data == {
            "user_input": True,
            "original_value_tag": original_value_tag,
        }


class TestIngredientSpellcheckAnnotator:
    @pytest.fixture
    def mock_save_ingredients(self, mocker) -> Mock:
        return mocker.patch("robotoff.insights.annotate.save_ingredients")

    @pytest.fixture
    def spellcheck_insight(self):
        return ProductInsightFactory(
            type="ingredient_spellcheck",
            data={
                "original": "List of ingredient",
                "correction": "List fo ingredients",
            },
        )

    def test_process_annotation(
        self,
        mock_save_ingredients: Mock,
        spellcheck_insight: ProductInsightFactory,
    ):
        user_data = {"annotation": "List of ingredients"}
        annotation_result = IngredientSpellcheckAnnotator.process_annotation(
            insight=spellcheck_insight,
            data=user_data,
        )
        assert annotation_result == UPDATED_ANNOTATION_RESULT
        assert "annotation" in spellcheck_insight.data
        mock_save_ingredients.assert_called()

    def test_process_annotate_no_user_data(
        self,
        mock_save_ingredients: Mock,
        spellcheck_insight: ProductInsightFactory,
    ):
        annotation_result = IngredientSpellcheckAnnotator.process_annotation(
            insight=spellcheck_insight,
        )
        assert annotation_result == UPDATED_ANNOTATION_RESULT
        assert "annotation" not in spellcheck_insight.data
        mock_save_ingredients.assert_called()


class TestNutrientExtractionAnnotator:
    SOURCE_IMAGE = "/872/032/603/7888/2.jpg"

    @pytest.fixture
    def mock_select_rotate_image(self, mocker) -> Mock:
        return mocker.patch("robotoff.insights.annotate.select_rotate_image")

    @pytest.fixture
    def nutrient_extraction_insight(self):
        return ProductInsightFactory(
            type="nutrient_extraction", source_image=self.SOURCE_IMAGE
        )

    def test_select_nutrition_image_no_image_id(
        self,
        mock_select_rotate_image: Mock,
        nutrient_extraction_insight: ProductInsightFactory,
    ):
        product: JSONType = {"images": {}, "lang": "fr"}
        NutrientExtractionAnnotator.select_nutrition_image(
            insight=nutrient_extraction_insight,
            product=product,
        )
        mock_select_rotate_image.assert_not_called()

    def test_select_nutrition_image_no_image_meta(
        self,
        mock_select_rotate_image: Mock,
        nutrient_extraction_insight: ProductInsightFactory,
    ):
        product: JSONType = {"images": {"2": {}}, "lang": "fr"}
        NutrientExtractionAnnotator.select_nutrition_image(
            insight=nutrient_extraction_insight,
            product=product,
        )
        mock_select_rotate_image.assert_not_called()

    def test_select_nutrition_image_already_selected(
        self,
        mock_select_rotate_image: Mock,
        nutrient_extraction_insight: ProductInsightFactory,
    ):
        product: JSONType = {
            "images": {
                "2": {"sizes": {"full": {"w": 1000, "h": 2000}}},
                "nutrition_fr": {"imgid": "2"},
            },
            "lang": "fr",
        }
        NutrientExtractionAnnotator.select_nutrition_image(
            insight=nutrient_extraction_insight,
            product=product,
        )
        mock_select_rotate_image.assert_not_called()

    def test_select_nutrition_image(
        self,
        mock_select_rotate_image: Mock,
        nutrient_extraction_insight: ProductInsightFactory,
    ):
        product = {
            "images": {"2": {"sizes": {"full": {"w": 1000, "h": 2000}}}},
            "lang": "fr",
        }
        NutrientExtractionAnnotator.select_nutrition_image(
            insight=nutrient_extraction_insight,
            product=product,
        )
        mock_select_rotate_image.assert_called_once_with(
            product_id=nutrient_extraction_insight.get_product_id(),
            image_id="2",
            image_key="nutrition_fr",
            rotate=None,
            crop_bounding_box=None,
            auth=None,
            is_vote=False,
            insight_id=nutrient_extraction_insight.id,
        )

    def test_select_nutrition_image_override_nutrition_image(
        self,
        mock_select_rotate_image: Mock,
        nutrient_extraction_insight: ProductInsightFactory,
    ):
        product = {
            "images": {
                "2": {"sizes": {"full": {"w": 1000, "h": 2000}}},
                # image 1 already selected, should be overridden
                "nutrition_fr": {"imgid": "1"},
            },
            "lang": "fr",
        }
        NutrientExtractionAnnotator.select_nutrition_image(
            insight=nutrient_extraction_insight,
            product=product,
        )
        mock_select_rotate_image.assert_called_once_with(
            product_id=nutrient_extraction_insight.get_product_id(),
            image_id="2",
            image_key="nutrition_fr",
            rotate=None,
            crop_bounding_box=None,
            auth=None,
            is_vote=False,
            insight_id=nutrient_extraction_insight.id,
        )

    def test_select_nutrition_image_with_rotation_and_nutrition_table_detection(
        self,
        mock_select_rotate_image: Mock,
        nutrient_extraction_insight: ProductInsightFactory,
    ):
        product = {
            "images": {"2": {"sizes": {"full": {"w": 1000, "h": 2000}}}},
            "lang": "fr",
        }
        rotation_data = {"rotation": 90}
        PredictionFactory(
            type=PredictionType.image_orientation,
            data=rotation_data,
            source_image=self.SOURCE_IMAGE,
        )
        image_model = ImageModelFactory(source_image=self.SOURCE_IMAGE)
        detection_data = {
            "objects": [
                {
                    "label": "nutrition-table",
                    "score": 0.550762104988098,
                    "bounding_box": [
                        0.06199073791503906,
                        0.20298996567726135,
                        0.4177824556827545,
                        0.9909706115722656,
                    ],
                },
            ]
        }
        ImagePredictionFactory(
            model_name=ObjectDetectionModel.nutrition_table.name,
            data=detection_data,
            image=image_model,
        )
        NutrientExtractionAnnotator.select_nutrition_image(
            insight=nutrient_extraction_insight,
            product=product,
        )
        mock_select_rotate_image.assert_called_once_with(
            product_id=nutrient_extraction_insight.get_product_id(),
            image_id="2",
            image_key="nutrition_fr",
            rotate=rotation_data["rotation"],
            crop_bounding_box=(
                202.98996567726135,
                1164.435088634491,
                990.9706115722656,
                1876.0185241699219,
            ),
            auth=None,
            is_vote=False,
            insight_id=nutrient_extraction_insight.id,
        )


class TestImageOrientationAnnotator:
    @pytest.fixture
    def mock_get_product(self, mocker):
        return mocker.patch("robotoff.insights.annotate.get_product")

    @pytest.fixture
    def mock_select_rotate_image(self, mocker) -> Mock:
        return mocker.patch("robotoff.insights.annotate.select_rotate_image")

    @pytest.fixture
    def mock_rotate_bounding_box(self, mocker) -> Mock:
        return mocker.patch("robotoff.insights.annotate.rotate_bounding_box")

    def test_process_annotation_missing_product(self, mock_get_product):
        mock_get_product.return_value = None

        insight = ProductInsightFactory(
            type="image_orientation",
            value_tag="right",
            data={
                "orientation": "right",
                "rotation": 270,
                "count": {"up": 1, "right": 19},
                "image_rev": "10",
                "image_key": "front_fr",
            },
            source_image="/1.jpg",
        )

        result = ImageOrientationAnnotator.process_annotation(insight)

        assert result == MISSING_PRODUCT_RESULT
        mock_get_product.assert_called_once()

    def test_process_annotation_not_selected_image(self, mock_get_product):
        mock_get_product.return_value = {
            "images": {
                "1": {
                    "imgid": "1",
                    "sizes": {"full": {"h": 1000, "w": 800}},
                },  # Not a selected image type (not front, ingredients, etc.)
            }
        }

        insight = ProductInsightFactory(
            type="image_orientation",
            value_tag="right",
            data={
                "orientation": "right",
                "rotation": 270,
                "count": {"up": 1, "right": 19},
                "image_key": "front_fr",
                "image_rev": "10",
            },
            source_image="/1.jpg",
        )

        result = ImageOrientationAnnotator.process_annotation(insight)

        assert result == OUTDATED_DATA_RESULT

    def test_process_annotation_success_with_absolute_coordinates(
        self, mock_get_product, mock_select_rotate_image, mock_rotate_bounding_box
    ):
        mock_get_product.return_value = {
            "images": {
                "1": {
                    "imgid": "1",
                    "sizes": {"full": {"h": 1000, "w": 800}},
                },
                "ingredients_it": {
                    "imgid": "1",
                    "x1": "100",
                    "y1": "200",
                    "x2": "600",
                    "y2": "800",
                    "rev": "7",
                    "sizes": {"full": {"h": 1000, "w": 800}},
                },
            }
        }

        mock_rotate_bounding_box.return_value = (300, 200, 700, 500)

        barcode = "1234567890123"
        server_type = "off"
        product_id = ProductIdentifier(barcode, ServerType.off)

        insight = ProductInsightFactory(
            barcode=barcode,
            server_type=server_type,
            type="image_orientation",
            value="right",
            data={
                "orientation": "right",
                "rotation": 270,
                "count": {"up": 1, "right": 19},
                "image_key": "ingredients_it",
                "image_rev": "7",
            },
            source_image=generate_image_path(product_id, "1"),
        )

        result = ImageOrientationAnnotator.process_annotation(insight)

        assert result == UPDATED_ANNOTATION_RESULT

        # Verify rotate_bounding_box was called with absolute coordinates
        mock_rotate_bounding_box.assert_called_once_with(
            (200.0, 100.0, 800.0, 600.0),  # y1, x1, y2, x2
            800,  # width
            1000,  # height
            270,  # rotation angle
        )

        mock_select_rotate_image.assert_called_once_with(
            product_id=product_id,
            image_id="1",
            image_key="ingredients_it",
            rotate=270,
            crop_bounding_box=(300, 200, 700, 500),
            auth=None,
            is_vote=False,
            insight_id=insight.id,
        )

    @pytest.mark.parametrize(
        "selected_image_data",
        [
            # Uncropped selected images can have "-1" or -1 (string or int) for
            # coordinates
            {"imgid": "1", "rev": "2", "x1": "-1", "y1": "-1", "x2": "-1", "y2": "-1"},
            {"imgid": "1", "rev": "2", "x1": -1, "y1": -1, "x2": -1, "y2": -1},
        ],
    )
    def test_uncropped_image_handling(
        self, selected_image_data, mock_get_product, mock_select_rotate_image
    ):
        mock_get_product.return_value = {
            "images": {
                "1": {
                    "imgid": "1",
                    "sizes": {"full": {"h": 1000, "w": 800}},
                },
                "front_en": selected_image_data,
            }
        }

        barcode = "1234567890123"
        server_type = "off"

        insight = ProductInsightFactory(
            barcode=barcode,
            server_type=server_type,
            type="image_orientation",
            value_tag="right",
            data={
                "orientation": "right",
                "rotation": 270,
                "count": {"up": 1, "right": 19},
                "image_rev": "2",
                "image_key": "front_en",
            },
            source_image="/1.jpg",
        )

        result = ImageOrientationAnnotator.process_annotation(insight)

        assert result == UPDATED_ANNOTATION_RESULT

        # Verify select_rotate_image was called with crop_bounding_box as None
        mock_select_rotate_image.assert_called_once()
        _, kwargs = mock_select_rotate_image.call_args
        assert kwargs["crop_bounding_box"] is None
