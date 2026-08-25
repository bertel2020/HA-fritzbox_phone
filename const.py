"""Constants for the FRITZ!Box phone integration."""

DOMAIN = "fritzbox_phone"

CONF_USE_TLS = "use_tls"
CONF_CALL_LIST_DAYS = "call_list_days"
CONF_CALL_LIST_MAX = "call_list_max"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLE_CALLMONITOR = "enable_call_monitor"
CONF_CALLMONITOR_PORT = "callmonitor_port"
CONF_PREFIXES = "prefixes"
CONF_PHONEBLOCK_ENABLED = "phoneblock_enabled"
CONF_PHONEBLOCK_USERNAME = "phoneblock_username"
CONF_PHONEBLOCK_PASSWORD = "phoneblock_password"
CONF_PHONEBLOCK_THRESHOLD = "phoneblock_spam_threshold"
CONF_REVERSE_LOOKUP_ENABLED = "reverse_lookup_enabled"

DEFAULT_CALL_LIST_DAYS = 7
DEFAULT_CALL_LIST_MAX = 50
DEFAULT_SCAN_INTERVAL = 120
DEFAULT_ENABLE_CALLMONITOR = True
# CallMonitor protocol port. Must be activated once per box by dialing
# #96*5* from any connected phone (deactivate with #96*4*).
DEFAULT_CALLMONITOR_PORT = 1012
DEFAULT_PHONEBLOCK_ENABLED = False
DEFAULT_PHONEBLOCK_THRESHOLD = 50
DEFAULT_COUNTRY_PREFIX = "+49"
DEFAULT_REVERSE_LOOKUP_ENABLED = False

# X_AVM-DE_OnTel CallList "Type" values (TR-064_Contact_SCPD.pdf, table 70)
CALL_TYPE_NAMES = {
    1: "incoming",
    2: "missed",
    3: "outgoing",
    9: "active_incoming",
    10: "rejected_incoming",
    11: "active_outgoing",
}
MISSED_CALL_TYPE = 2
OUTGOING_CALL_TYPE = 3

# Port values that identify fax / answering-machine calls in the call list
# (TR-064_Contact_SCPD.pdf, section 5.2 Call List Content).
FAX_PORT = 5
TAM_PORT = 6
TAM_PORT_RANGE = range(40, 50)

ATTR_MESSAGE_INDEX = "message_index"
ATTR_READ = "read"
ATTR_FILENAME = "filename"

SERVICE_MARK_MESSAGE_READ = "mark_message_read"
SERVICE_DELETE_MESSAGE = "delete_message"
SERVICE_DOWNLOAD_MESSAGE = "download_message"

# Lovelace card frontend resource, served from the integration's www/ folder.
CARD_JS_FILENAME = "fritzbox-phone-card.js"
CARD_JS_URL = "/fritzbox_phone_static/fritzbox-phone-card.js"

# CallMonitor sensor states (mirrors homeassistant.components.fritzbox_callmonitor)
CALLMONITOR_STATE_IDLE = "idle"
CALLMONITOR_STATE_RINGING = "ringing"
CALLMONITOR_STATE_DIALING = "dialing"
CALLMONITOR_STATE_TALKING = "talking"
