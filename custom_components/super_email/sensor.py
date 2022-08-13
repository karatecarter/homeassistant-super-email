import asyncio
import email
from imaplib2 import IMAP4_SSL
import os

import logging
from datetime import timedelta
from threading import *
from typing import Any, Optional

import imaplib2
from sqlalchemy import true

# import pandas as pd
from homeassistant import config_entries, core
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import (
    HomeAssistantType,
)


from .const import DOMAIN
from .save_email import save_email
from .send_email import send_mail

_LOGGER = logging.getLogger(__name__)
# Time between updating data from Google
SCAN_INTERVAL = timedelta(minutes=60)


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

    sensors = [
        EmailSensor(
            hass,
            config["imap_server"],
            config["imap_port"],
            config["username"],
            config["password"],
            config["folder"],
        )
    ]
    async_add_entities(sensors, update_before_add=True)


class EmailSensor(Entity):
    """Sensor to detect when there is new email"""

    def __init__(self, hass: HomeAssistantType, host, port, username, password, folder):
        super().__init__()
        self._hass = hass
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._folder = folder

        self._imap_session: IMAP4_SSL = None
        self._idler: Idler = None

        self._name = "email"
        self._state = None
        self._available = True
        self._attr_unique_id = username

        self._attrs: dict[str, Any] = {}

    @property
    def imap_session(self) -> IMAP4_SSL:
        return self._imap_session

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> Optional[str]:
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs

    def connect_imap(self):
        """Connect to IMAP server and start monitoring email folder"""
        self._imap_session = imaplib2.IMAP4_SSL(self._host, self._port)
        self._imap_session.login(self._username, self._password)

        self._imap_session.select(self._folder)

    def try_disconnect(self):
        if self._imap_session.state == "SELECTED":
            try:
                self._imap_session.close()
            except Exception:
                pass
        if self._imap_session.state != "LOGOUT":
            try:
                self._imap_session.logout()
            except Exception:
                pass

    async def async_try_reconnect(self, wait: int = 0):
        self._available = False
        self.try_disconnect()

        if wait > 0:
            _LOGGER.info("Reconnecting in %s seconds...", wait)
            await asyncio.sleep(wait)

        try:
            _LOGGER.info("Reconnecting...")
            self.connect_imap()
            self._available = True
            self.schedule_update_ha_state(True)
        except Exception as ex:
            _LOGGER.error(ex)
            self.schedule_update_ha_state(False)
            self._hass.async_create_task(
                self.async_try_reconnect(wait=60)
            )  # try again in 1 minute

    def start_monitor(self):
        if self._imap_session is None:
            self.connect_imap()

        if self._idler is None:
            _LOGGER.debug("Starting email monitor")
            self._idler = Idler(self)
            self._idler.start()

    def process_new_email(self):
        self.schedule_update_ha_state(True)

    async def async_update(self):
        _LOGGER.debug("async_update")
        if self._imap_session is None:
            try:
                self.connect_imap()
            except Exception as ex:
                _LOGGER.error(ex)
                self._available = False
                await self.async_try_reconnect()
                return

        typ, data = self._imap_session.search(None, "ALL")

        id_list = data[0].split()

        latest_id = id_list[len(id_list) - 1]

        typ, msg = self._imap_session.fetch(latest_id, "(RFC822)")
        for response in msg:
            if isinstance(response, tuple):
                msg_data = email.message_from_bytes(response[1])

                # Retrieving the senders email
                sender = msg_data["From"]
                subject = msg_data["Subject"]
                date = msg_data["Date"]
                to = msg_data["To"]

                self._state = subject

        # self._attrs = msg_data
        self._attrs["from"] = sender
        self._attrs["date"] = date
        self._attrs["subject"] = subject
        self._attrs["to"] = to
        self._attrs["body_text"] = ""
        self._attrs["body_html"] = ""

        for part in msg_data.walk():
            if part.get_content_type() == "text/plain":
                self._attrs["body_text"] = part.get_payload()
            if part.get_content_type() == "text/html":
                self._attrs["body_html"] = part.get_payload()

        self._available = True
        self.start_monitor()

        # self._hass.async_add_executor_job(self.async_start_monitor)


# This is the threading object that does all the waiting on
# the event
class Idler(object):
    def __init__(self, email_sensor: EmailSensor):
        self.thread = Thread(target=self.idle)
        self.email_sensor = email_sensor
        self.event = Event()

    def start(self):
        self.thread.start()

    def stop(self):
        # This is a neat trick to make thread end. Took me a
        # while to figure that one out!
        self.event.set()

    def join(self):
        self.thread.join()

    def idle(self):
        # Starting an unending loop here
        while True:
            # This is part of the trick to make the loop stop
            # when the stop() command is given
            if self.event.isSet():
                return
            if not self.email_sensor._available:
                continue

            self.needsync = False
            # A callback method that gets called when a new
            # email arrives. Very basic, but that's good.
            def callback(args):
                _LOGGER.debug("IMAP event")
                if not self.event.isSet():
                    self.needsync = True
                    self.event.set()

            # Do the actual idle call. This returns immediately,
            # since it's asynchronous.
            try:
                _LOGGER.debug("Waiting for IMAP events")
                self.email_sensor._imap_session.idle(callback=callback)
            except IMAP4_SSL.abort as ex:
                # connection lost, kill thread and attempt restart
                _LOGGER.error(ex)
                asyncio.run_coroutine_threadsafe(
                    self.email_sensor.async_try_reconnect(),
                    self.email_sensor._hass.loop,
                )
                self.email_sensor._available = False
                continue
            # This waits until the event is set. The event is
            # set by the callback, when the server 'answers'
            # the idle call and the callback function gets
            # called.
            self.event.wait()
            # Because the function sets the needsync variable,
            # this helps escape the loop without doing
            # anything if the stop() is called. Kinda neat
            # solution.
            if self.needsync:
                self.event.clear()
                self.dosync()

    # The method that gets called when a new email arrives.
    # Replace it with something better.
    def dosync(self):
        self.email_sensor.process_new_email()
