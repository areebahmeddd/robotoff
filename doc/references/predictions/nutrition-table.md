# Nutrition photo selection

Every product should have a nutrition photo selected if nutrition facts are visible on the packaging. For multilingual products, we only want a nutrition table to be selected for the main language of the product to avoid unnecessary image duplication, except in the rare cases where we have distinct table for different languages.

We detect nutrition tables using a mix of string matching (*regex*) [^nutrient_mention_insight] and machine learning detections. We use `nutrient_mention` insights to fetch all nutrient mentions, in all supported languages:

- nutrient names ("sugar", "carbohydrates", "nutritional information", "energy",...)
- nutrient values

We also use `nutrient` insights  [^nutrient_insight], that detect nutrient name and values that are consecutive in the OCR string, to assign a higher priority to images that also  `nutrient` insights in addition to `nutrient_mention` insights (`priority=1` instead of `priority=2`).

The detected nutrient names are associated with one or more language (ex: if we detect 'energie', it may be in French, German or Dutch). We check for each image and each detected language if the following rules applies, in which case the image is a candidate for selection as a nutrition table photo [^nutrition_image_importer]:

- we must have at least 4 nutrient name mentions ("sugar", "energy",...) in the target language
- we must have at least 3 nutrient value mentions ("15 g", "252 kJ",...)
- we must have at least one energy nutrient value (value ending with "kJ" or "kcal")
- the detected language must be the product main language

If it exist, we also use the `nutrition-table` object detector prediction to find a crop of the nutrition table. We only use the cropping information if there is only one nutrition table detected with confidence `>=0.9`. 

If all these conditions apply, we generate an insight. There is maximum one insight generated by product.
Note that we generate candidates using the most recent images first (images are sorted by decreasing image IDs), so that the most recent images are considered first: we want the most up-to-date photo possible for nutrition table.

[^nutrient_mention_insight]: see `find_nutrient_mentions` in `robotoff.prediction.ocr.nutrient`
[^nutrient_insight]: see `find_nutrient_values` in `robotoff.prediction.ocr.nutrient`
[^nutrition_image_importer]: see `NutritionImageImporter.generate_candidates_for_image` in `robotoff.insights.importer`