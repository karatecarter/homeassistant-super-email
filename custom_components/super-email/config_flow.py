from asyncio.log import logger
import imaplib
import logging
import smtplib
from typing import Any, Dict, Optional
from homeassistant import config_entries

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from .const import DOMAIN

#
#
CONF_SCHEMA = vol.Schema(
    {
        vol.Required(
            "smtp_server",
            msg="SMTP Server (ex. 'smtp.gmail.com')",
            default="smtp.gmail.com",
        ): cv.string,
        vol.Required("smtp_port", msg="SMTP Port", default=587): cv.positive_int,
        vol.Required(
            "imap_server",
            msg="IMAP Server (ex. 'imap.gmail.com')",
            default="imap.gmail.com",
        ): cv.string,
        vol.Required("imap_port", msg="IMAP Port", default=993): cv.positive_int,
        vol.Required("username"): cv.string,
        vol.Required("password"): cv.string,
    }
)


_LOGGER = logging.getLogger(__name__)


class SuperEmailConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Super Email config flow."""

    api_key: Dict[str, str] = {}

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        """Invoked when a user initiates a flow via the user interface."""
        errors: Dict[str, str] = {}
        key: Dict[str, str] = {}

        if user_input is not None:

            try:
                smtphost = user_input["smtp_server"]
                smtpport = user_input["smtp_port"]
                imaphost = user_input["imap_server"]
                imapport = user_input["imap_port"]
                username = user_input["username"]
                password = user_input["password"]

                smtp = smtplib.SMTP(smtphost, smtpport)
                smtp.starttls()
                smtp.login(username, password)
                smtp.close()

                imap = imaplib.IMAP4_SSL(imaphost, port=imapport)
                imap.login(username, password)
                imap.logout()

            except Exception as ex:
                logger.error(ex)
                errors["base"] = "auth"

            if not errors:
                # Input is valid, set data.
                # self.data = user_input
                self.api_key = key
                return self.async_create_entry(title="Super Email", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=CONF_SCHEMA, errors=errors
        )
