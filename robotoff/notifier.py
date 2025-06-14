import json
import operator

import requests
from requests.exceptions import ConnectionError as RequestConnectionError
from requests.exceptions import JSONDecodeError

from robotoff import settings
from robotoff.models import ImageModel, LogoAnnotation, ProductInsight, crop_image_url
from robotoff.types import (
    InsightType,
    JSONType,
    LogoLabelType,
    Prediction,
    ProductIdentifier,
    ServerType,
)
from robotoff.utils import get_logger, http_session

logger = get_logger(__name__)


class SlackException(Exception):
    pass


class NotifierInterface:
    """NotifierInterface is an interface for posting
    Robotoff-related alerts and notifications
    to various channels.
    """

    # Note: we do not use abstract methods,
    # for a notifier might choose to only implements a few

    def notify_image_flag(
        self,
        predictions: list[Prediction],
        source_image: str,
        product_id: ProductIdentifier,
    ):
        pass

    def notify_automatic_processing(self, insight: ProductInsight):
        pass

    def send_logo_notification(
        self, logo: LogoAnnotation, probs: dict[LogoLabelType, float]
    ):
        pass


class NotifierFactory:
    """NotifierFactory is responsible for creating a notifier to post
    notifications to."""

    @staticmethod
    def get_notifier() -> NotifierInterface:
        notifiers: list[NotifierInterface] = []
        token = settings.slack_token()
        if token == "":
            # use a Noop notifier to get logs for tests and dev
            notifiers.append(NoopSlackNotifier())
        else:
            notifiers.append(SlackNotifier(token))
        moderation_service_url: str | None = settings.IMAGE_MODERATION_SERVICE_URL
        if moderation_service_url:
            notifiers.append(ImageModerationNotifier(moderation_service_url))
        if len(notifiers) == 1:
            return notifiers[0]
        else:
            return MultiNotifier(notifiers)


HUMAN_FLAG_LABELS = {
    "face",
    "head",
    "selfie",
    "hair",
    "forehead",
    "chin",
    "cheek",
    "tooth",
    "eyebrow",
    "ear",
    "neck",
    "nose",
    "facial expression",
    "child",
    "baby",
    "human",
}


def _sensitive_image(flag_type: str, flagged_label: str) -> bool:
    """Determines whether the given flagged image should be considered as
    sensitive."""
    is_human = flagged_label in HUMAN_FLAG_LABELS
    return (
        is_human and flag_type == "label_annotation"
    ) or flag_type == "safe_search_annotation"


def _slack_message_block(
    message_text: str, with_image: str | None = None
) -> list[dict]:
    """Formats given parameters into a Slack message block."""
    block = {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": message_text,
        },
    }

    if with_image:
        block["accessory"] = {
            "type": "image",
            "image_url": with_image,
            "alt_text": "-",
        }
    return [block]


class MultiNotifier(NotifierInterface):
    """Aggregate multiple notifiers in one instance

    See NotifierInterface for methods documentation

    :param notifiers: the notifiers to dispatch to
    """

    def __init__(self, notifiers: list[NotifierInterface]):
        self.notifiers: list[NotifierInterface] = notifiers

    def _dispatch(self, function_name: str, *args, **kwargs):
        """dispatch call to function_name to all notifiers"""
        for notifier in self.notifiers:
            fn = getattr(notifier, function_name)
            fn(*args, **kwargs)

    def notify_image_flag(
        self,
        predictions: list[Prediction],
        source_image: str,
        product_id: ProductIdentifier,
    ):
        self._dispatch("notify_image_flag", predictions, source_image, product_id)

    def notify_automatic_processing(self, insight: ProductInsight):
        self._dispatch("notify_automatic_processing", insight)

    def send_logo_notification(
        self, logo: LogoAnnotation, probs: dict[LogoLabelType, float]
    ):
        self._dispatch("send_logo_notification", logo, probs)


class ImageModerationNotifier(NotifierInterface):
    """Notifier to dispatch to image moderation server

    :param service_url: base url for image moderation service
    """

    def __init__(self, service_url):
        self.service_url = service_url.rstrip("/")

    def notify_image_flag(
        self,
        predictions: list[Prediction],
        source_image: str,
        product_id: ProductIdentifier,
    ):
        """Send image to the moderation server so that a human can moderate
        it"""
        if not predictions:
            return

        image_url = settings.BaseURLProvider.image_url(
            product_id.server_type, source_image
        )
        image_id = source_image.rsplit("/", 1)[-1].split(".", 1)[0]
        for prediction in predictions:
            reason = "other"
            prediction_subtype = prediction.data.get("type")
            prediction_label = prediction.data.get("label")
            if prediction_subtype == "safe_search_annotation":
                reason = "inappropriate"
            elif (
                prediction_subtype == "label_annotation"
                and prediction_label in HUMAN_FLAG_LABELS
            ):
                reason = "human"
            elif prediction_subtype == "face_annotation":
                reason = "human"
            elif prediction_subtype == "text" and prediction_label == "beauty":
                # Don't send beauty text detection to moderation service for
                # now
                continue

            if "label" in prediction.data:
                if prediction_subtype == "text":
                    comment = f"Robotoff detection: '{prediction.data['text']}' ({prediction.data['label']})"
                else:
                    comment = f"Robotoff detection: {prediction.data['label']}"
            else:
                comment = "Robotoff detection"

            data = {
                "barcode": product_id.barcode,
                "type": "image",
                "url": image_url,
                "user_id": "roboto-app",
                "source": "robotoff",
                "confidence": prediction.confidence,
                "image_id": image_id,
                "flavor": product_id.server_type.value,
                "reason": reason,
                "comment": comment,
            }
            try:
                logger.info("Notifying image %s to moderation service", image_url)
                http_session.post(self.service_url, json=data)
            except Exception:
                logger.exception(
                    "Error while notifying image to moderation service",
                    extra={
                        "params": data,
                        "url": image_url,
                        "barcode": product_id.barcode,
                    },
                )


class SlackNotifier(NotifierInterface):
    """Notifier to send messages on specific slack channels"""

    # Slack channel IDs.
    ROBOTOFF_ALERT_CHANNEL = "CGKPALRCG"  # robotoff-alerts-annotations

    BASE_URL = "https://slack.com/api"
    POST_MESSAGE_URL = BASE_URL + "/chat.postMessage"
    COLLAPSE_LINKS_PARAMS = {
        "unfurl_links": False,
        "unfurl_media": False,
    }

    def __init__(self, slack_token: str):
        """Should not be called directly, use the NotifierFactory instead."""
        self.slack_token = slack_token

    def notify_automatic_processing(self, insight: ProductInsight):
        server_type = ServerType[insight.server_type]
        product_url = (
            f"{settings.BaseURLProvider.world(server_type)}/product/{insight.barcode}"
        )

        if insight.source_image:
            if insight.data and "bounding_box" in insight.data:
                image_url = crop_image_url(
                    server_type,
                    insight.source_image,
                    insight.data.get("bounding_box"),
                )
            else:
                image_url = settings.BaseURLProvider.image_url(
                    server_type, insight.source_image
                )
            metadata_text = f"(<{product_url}|product>, <{image_url}|source image>)"
        else:
            metadata_text = f"(<{product_url}|product>)"

        value = insight.value or insight.value_tag

        if insight.type in {
            InsightType.product_weight.name,
            InsightType.expiration_date.name,
        }:
            text = f"The {insight.type} `{value}` (match: `{insight.data['raw']}`) was automatically added to product {insight.barcode}"
        else:
            text = f"The `{value}` {insight.type} was automatically added to product {insight.barcode}"

        message = _slack_message_block(f"{text} {metadata_text}")
        self._post_message(
            message, self.ROBOTOFF_ALERT_CHANNEL, **self.COLLAPSE_LINKS_PARAMS
        )

    def _get_base_params(self) -> JSONType:
        return {
            "username": "robotoff-bot",
            "token": self.slack_token,
            "icon_url": "https://s3-us-west-2.amazonaws.com/slack-files2/"
            "bot_icons/2019-03-01/565595869687_48.png",
        }

    def send_logo_notification(
        self, logo: LogoAnnotation, probs: dict[LogoLabelType, float]
    ):
        crop_url = logo.get_crop_image_url()
        prob_text = "\n".join(
            (
                f"{label[0]} - {label[1]}: {prob:.2g}"
                for label, prob in sorted(
                    probs.items(), key=operator.itemgetter(1), reverse=True
                )
            )
        )
        image_model: ImageModel = logo.image_prediction.image
        product_id = image_model.get_product_id()
        base_off_url = settings.BaseURLProvider.world(product_id.server_type)
        text = (
            f"Prediction for <{crop_url}|image> "
            f"(<https://hunger.openfoodfacts.org/logos?logo_id={logo.id}|annotate logo>, "
            f"<{base_off_url}/product/{product_id.barcode}|product>):\n{prob_text}"
        )
        self._post_message(_slack_message_block(text), self.ROBOTOFF_ALERT_CHANNEL)

    def _post_message(
        self,
        blocks: list[dict],
        channel: str,
        **kwargs,
    ):
        try:
            params: JSONType = {
                **(self._get_base_params()),
                "channel": channel,
                "blocks": json.dumps(blocks),
                **kwargs,
            }

            r = http_session.post(self.POST_MESSAGE_URL, data=params)
            response_json = _get_slack_json(r)
            return response_json
        except (RequestConnectionError, JSONDecodeError) as e:
            logger.info(
                "An exception occurred when sending a Slack notification", exc_info=e
            )
        except Exception as e:
            logger.error(
                "An exception occurred when sending a Slack notification", exc_info=e
            )


class NoopSlackNotifier(SlackNotifier):
    """NoopSlackNotifier is a NOOP SlackNotifier used in dev/local executions
    of Robotoff."""

    def __init__(self):
        super().__init__("")

    def _post_message(
        self,
        blocks: list[dict],
        channel: str,
        **kwargs,
    ):
        """Overrides the actual posting to Slack with logging of the args that
        would've been posted."""
        logger.info(
            "Alerting on slack channel '%s', with message:\n%s\nand additional args:\n%s",
            channel,
            blocks,
            kwargs,
        )


def _get_slack_json(response: requests.Response) -> JSONType:
    json_data = response.json()

    if not response.ok:
        raise SlackException(
            "Non-200 status code from Slack: "
            "{}, response: {}"
            "".format(response.status_code, json_data)
        )

    if not json_data.get("ok", False):
        raise SlackException("Non-ok response: {}".format(json_data))

    return json_data
