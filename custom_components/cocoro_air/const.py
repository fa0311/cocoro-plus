"""Constants for COCORO AIR & WASH."""

from datetime import timedelta
from enum import StrEnum

DOMAIN = "cocoro_air"
CONF_DEVICES = "devices"
BASE_URL = "https://cocoroplusapp.jp.sharp"
AUTH_HOST = "auth.cocoromembers.jp.sharp"
REQUEST_TIMEOUT = 30
UPDATE_INTERVAL = timedelta(seconds=30)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class Service(StrEnum):
    """Supported COCORO services."""

    AIR = "air"
    WASH = "wash"


OBJECT_IDS = {Service.AIR: "0x013501", Service.WASH: "0x03d301"}
