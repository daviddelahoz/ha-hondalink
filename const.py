from datetime import timedelta

DOMAIN = "hondalink"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_PIN = "pin"
CONF_VIN = "vin"
CONF_NAME = "name"
CONF_CLIENT_REG_KEY = "client_reg_key"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"
CONF_COUNTRY = "country"
CONF_LANGUAGE = "language"
CONF_HIDAS_IDENT = "hidas_ident"
CONF_DEVICE_ID = "device_id"
CONF_SESSION_ID = "session_id"
CONF_VEHICLE_INFO = "vehicle_info"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_LOCK_COMMAND = "lock_command"
CONF_UNLOCK_COMMAND = "unlock_command"
CONF_BRAND = "brand"

DEFAULT_NAME = "HondaLink"
BRAND_HONDA = "honda"
BRAND_ACURA = "acura"
DEFAULT_BRAND = BRAND_HONDA
DEFAULT_COUNTRY = "US"
DEFAULT_LANGUAGE = "en"
DEFAULT_SCAN_INTERVAL = 3
DEFAULT_LOCK_COMMAND = "alk"
DEFAULT_UNLOCK_COMMAND = "dulk"
LEGACY_LOCK_COMMAND = "lck"
LEGACY_UNLOCK_COMMAND = "ulk"
DEFAULT_DASHBOARD_FILTERS = [
    "DigitalTwin",
    "VEHICLE RANGE",
    "odometer",
    "TIRE PRESSURE",
]
# Filter list the AcuraLink Android app 5.5.2 sends for MY22+ vehicles (2GX platform).
ACURA_DASHBOARD_FILTERS = [
    "doorStatus",
    "lightStatus",
    "windowStatus",
    "tireStatus",
    "odometer",
    "fuelLevel",
    "warningLamps",
    "oilLife",
    "maintenanceMinder",
    "temperature",
    "remoteEngineStart",
]
DASHBOARD_FILTER_SETS = (
    DEFAULT_DASHBOARD_FILTERS,
    ["DigitalTwin"],
    [],
)

CLIENT_ID = "HondaLinkAndroidApp0074"
CLIENT_SECRET = "rETFrZcLyUycsSblksCP"
DEVICE_DESCRIPTION = "Android"
APP_USER_AGENT = "HondaLink/5.0.51 (Android)"

BRANDS = {
    BRAND_HONDA: {
        "name": "HondaLink",
        "make": "Honda",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "user_agent": APP_USER_AGENT,
        "business_id": "HONDALINK CONNECT",
        "system_id": "com.honda.hondalink.cv_android",
    },
    # Values taken from the AcuraLink Android app 5.5.2 (com.acura.acuralink.connect).
    BRAND_ACURA: {
        "name": "AcuraLink",
        "make": "Acura",
        "client_id": "AcuraLinkAndroidApp2366",
        "client_secret": "IkikWOxSbDhYJKrbfdOA",
        "user_agent": "AcuraLink/5.5.2 (Android)",
        "business_id": "ACURALINK CONNECT",
        "system_id": "com.acura.acuralink.cv_android",
    },
}

IDENTITY_BASE = "https://identity.services.honda.com"
API_BASE = "https://wsc.hondaweb.com"
PUSH_TOKEN_PATH = "/REST/CIG/services/1.0/token"

HONDALINK_BUSINESS_ID = "HONDALINK CONNECT"
HONDALINK_SYSTEM_ID = "com.honda.hondalink.cv_android"
HONDA_HEADER_VERSION = "1.0"

UPDATE_INTERVAL = timedelta(minutes=DEFAULT_SCAN_INTERVAL)

DATA_API = "api"
DATA_COORDINATOR = "coordinator"
