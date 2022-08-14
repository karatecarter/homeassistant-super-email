"""Sensors for super_email Home Assistant integration"""
import asyncio
import email
from typing import Any, Optional
import os
import logging
from datetime import timedelta
from threading import Thread, Event
from imaplib2 import IMAP4_SSL
import imaplib2

# import pandas as pd
from homeassistant import config_entries, core
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import (
    HomeAssistantType,
)
from homeassistant.helpers.entity_platform import current_platform
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

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

    def send_email(call):
        host = config["smtp_server"]
        port = config["smtp_port"]
        username = config["username"]
        password = config["password"]
        folder = call.data.get("folder")
        sender = call.data.get("sender")
        recipient = call.data.get("recipient")
        subject = call.data.get("subject")
        body = call.data.get("body", "")
        delete_files = call.data.get("delete_files_after_sending")

        files = []
        for filename in os.listdir(folder):
            files.append(folder + "/" + filename)

        send_mail(
            sender,
            recipient,
            subject,
            body,
            files,
            server=host,
            port=port,
            username=username,
            password=password,
        )

        if delete_files:
            for file in files:
                os.remove(file)

    platform = current_platform.get()
    platform.async_register_entity_service(
        "save_latest_email",
        {
            vol.Required("save_to_folder"): cv.string,
            vol.Required("filename"): cv.string,
        },
        "save_latest_email",
    )

    hass.services.async_register(DOMAIN, "send_email", send_email)

    # hass.services.async_register(DOMAIN, "save_latest_email", save_latest_email)

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
        self._attr_name = host + "_" + folder

        self._imap_session: IMAP4_SSL = None
        self._idler: Idler = None

        self._state = None
        self._available = True
        self._attr_unique_id = "super_email_" + host + "_" + folder

        self._attrs: dict[str, Any] = {}

    async def save_latest_email(self, save_to_folder, filename):
        """Save the latest email to a file"""
        emailfolder = self._folder

        host = self._host
        port = self._port
        username = self._username
        password = self._password
        save_email(
            host, port, username, password, emailfolder, save_to_folder, filename
        )

    @property
    def imap_session(self) -> IMAP4_SSL:
        """IMAP session to get emails from"""
        return self._imap_session

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

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
        """Close the current IMAP session, ignore errors"""
        if self._imap_session.state == "SELECTED":
            try:
                self._imap_session.close()
            except Exception:  # pylint: disable=broad-except
                pass
        if self._imap_session.state != "LOGOUT":
            try:
                self._imap_session.logout()
            except Exception:  # pylint: disable=broad-except
                pass

    async def async_try_reconnect(self, wait: int = 0):
        """Disconnect and reconnect the IMAP session"""
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
        except Exception as ex:  # pylint: disable=broad-except
            _LOGGER.error(ex)
            self.schedule_update_ha_state(False)
            self._hass.async_create_task(
                self.async_try_reconnect(wait=60)
            )  # try again in 1 minute

    def start_monitor(self):
        """Start a new thread to monitor emails if one doesn't already exist"""
        if self._imap_session is None:
            self.connect_imap()

        if self._idler is None:
            _LOGGER.debug("Starting email monitor")
            self._idler = Idler(self, self._hass)
            self._idler.start()

    def process_new_email(self):
        """Called from monitor thread when an IMAP event is received"""
        self.schedule_update_ha_state(True)

    async def async_update(self):
        """Updates the sensor state"""
        _LOGGER.debug("async_update")
        if self._imap_session is None:
            try:
                self.connect_imap()
            except Exception as ex:  # pylint: disable=broad-except
                _LOGGER.error(ex)
                self._available = False
                await self.async_try_reconnect()
                return

        typ, data = self._imap_session.search(  # pylint: disable=unused-variable
            None, "ALL"
        )

        id_list = data[0].split()

        latest_id = id_list[len(id_list) - 1]

        sender = ""
        date = ""
        subject = ""
        recipient = ""

        typ, msg = self._imap_session.fetch(latest_id, "(RFC822)")
        for response in msg:
            if isinstance(response, tuple):
                msg_data = email.message_from_bytes(response[1])

                # Retrieving the senders email
                sender = msg_data["From"]
                subject = msg_data["Subject"]
                date = msg_data["Date"]
                recipient = msg_data["To"]

        # self._attrs = msg_data
        self._attrs["from"] = sender
        self._attrs["date"] = date
        self._attrs["subject"] = subject
        self._attrs["to"] = recipient
        self._attrs["body_text"] = ""
        self._attrs["body_html"] = ""
        self._state = subject

        if date == "":
            self._available = False
        else:
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
    """This is the threading object that does all the waiting on the event"""

    def __init__(self, email_sensor: EmailSensor, hass: HomeAssistantType):
        self.thread = Thread(target=self.idle)
        self.email_sensor = email_sensor
        self.event = Event()
        self.needsync = False
        self._hass = hass

    def start(self):
        """Starts the thread"""
        self.thread.start()

    def stop(self):
        """Ends the thread"""
        # This is a neat trick to make thread end. Took me a
        # while to figure that one out!
        self.event.set()

    def join(self):
        """Join the thread"""
        self.thread.join()

    def idle(self):
        """Thread loop - Starting an unending loop here"""
        while True:
            # This is part of the trick to make the loop stop
            # when the stop() command is given
            if self.event.isSet():
                return
            if not self.email_sensor.available:
                continue

            self.needsync = False
            # A callback method that gets called when a new
            # email arrives. Very basic, but that's good.
            def callback(args):
                _LOGGER.debug("IMAP event %s", args)
                if not self.event.isSet():
                    self.needsync = True
                    self.event.set()

            # Do the actual idle call. This returns immediately,
            # since it's asynchronous.
            try:
                _LOGGER.debug("Waiting for IMAP events")
                self.email_sensor.imap_session.idle(callback=callback)
            except IMAP4_SSL.abort as ex:
                # connection lost, kill thread and attempt restart
                _LOGGER.error(ex)
                asyncio.run_coroutine_threadsafe(
                    self.email_sensor.async_try_reconnect(),
                    self._hass.loop,
                )
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

    def dosync(self):
        """The method that gets called when a new email arrives or the idle event times out"""
        self.email_sensor.process_new_email()
