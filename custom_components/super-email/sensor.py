import os

import logging
from config.custom_components.super_email.save_email import save_email
from config.custom_components.super_email.send_email import send_mail

# import pandas as pd
from homeassistant import config_entries, core
from datetime import timedelta
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
# Time between updating data from Google
SCAN_INTERVAL = timedelta(minutes=1)


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    """Setup sensors from a config entry created in the integrations UI."""
    config = hass.data[DOMAIN][config_entry.entry_id]

    def send_emails(call):
        host = config["smtp_server"]
        port = config["smtp_port"]
        username = config["username"]
        password = config["password"]
        files = []
        for filename in os.listdir("config/uber"):
            files.append("config/uber/" + filename)

        send_mail(
            "Daniel Carter <everkleer80@gmail.com>",
            "Daniel Carter <everkleer80@gmail.com>",
            "Uber Expense",
            "",
            files,
            server=host,
            port=port,
            username=username,
            password=password,
        )

    def save_latest_email(call):
        folder = call.data.get("folder", "INBOX")
        filename = call.data.get("filename", "")

        host = config["imap_server"]
        port = config["imap_port"]
        username = config["username"]
        password = config["password"]
        save_email(host, port, username, password, folder, filename)

    hass.services.async_register(DOMAIN, "send_emails", send_emails)

    hass.services.async_register(DOMAIN, "save_latest_email", save_latest_email)
