"""Config flow for U-Prox."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .api import UProxApi, UProxApiError, UProxInvalidAuth
from .const import CONF_PANEL_SERIAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class UProxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a U-Prox cloud panel."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        """Authenticate and retrieve panels available to the account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                api = UProxApi(self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
                await api.async_login()
                panels = await api.async_get_panels()
            except UProxInvalidAuth as err:
                _LOGGER.warning("U-Prox cloud login rejected (%s)", err)
                errors["base"] = "invalid_auth"
            except (UProxApiError, TimeoutError) as err:
                _LOGGER.warning("U-Prox setup failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                choices = {
                    str(panel["serial_number"]): str(panel.get("name") or panel["serial_number"])
                    for panel in panels
                    if panel.get("serial_number") is not None
                }
                if not choices:
                    errors["base"] = "no_panels"
                else:
                    self._login_data = dict(user_input)
                    self._panel_choices = choices
                    return await self.async_step_panel()

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_panel(self, user_input: dict | None = None):
        """Let the user choose a panel for this config entry."""
        if user_input is not None:
            panel_serial = user_input[CONF_PANEL_SERIAL]
            await self.async_set_unique_id(panel_serial)
            self._abort_if_unique_id_configured()
            panel_name = self._panel_choices[panel_serial]
            return self.async_create_entry(
                title=panel_name,
                data={
                    **self._login_data,
                    CONF_PANEL_SERIAL: int(panel_serial),
                    "panel_name": panel_name,
                },
            )

        return self.async_show_form(
            step_id="panel",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PANEL_SERIAL): vol.In(self._panel_choices),
                }
            ),
        )