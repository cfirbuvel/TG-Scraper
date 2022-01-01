import ipaddress

from telethon.crypto import AuthKey
from telethon.sessions.string import StringSession as TelethonStringSession


class StringSession(TelethonStringSession):

    @classmethod
    def from_parts(cls, dc_id, ip, port, key=None):
        self = cls()
        self._server_address = ipaddress.ip_address(ip).compressed
        self._dc_id = dc_id
        self._port = port
        if key:
            self._auth_key = AuthKey(key)
        return self.save()
