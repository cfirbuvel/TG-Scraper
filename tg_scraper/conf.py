from configparser import ConfigParser
import enum


class LastSeenEnum(enum.IntEnum):
    ANY_TIME = 0
    RECENTLY = 1
    WITHIN_A_WEEK = 7
    WITHIN_A_MONTH = 30

    @property
    def verbose_name(self):
        return self.name.replace('_', ' ').capitalize()


class Settings:
    section = 'main'

    def __init__(self):
        self.filename = 'config.ini'
        self.config = ConfigParser()
        self.config.read(self.filename)
        self.token = self.config.get(self.section, 'bot_token')

    def save_val(self, name, val):
        self.config.set(self.section, name, val)
        with open(self.filename, 'w') as f:
            self.config.write(f)

    @property
    def last_seen_filter(self):
        return self.config.getint(self.section, 'last_seen_filter', fallback=0)

    @last_seen_filter.setter
    def last_seen_filter(self, val):
        self.save_val('last_seen_filter', str(val))

    @property
    def join_delay(self):
        return self.config.getint(self.section, 'join_delay', fallback=60)

    @join_delay.setter
    def join_delay(self, val):
        self.save_val('join_delay', str(val))

    @property
    def invites_limit(self):
        low = self.config.getint(self.section, 'inv_limit_low', fallback=20)
        high = self.config.getint(self.section, 'inv_limit_high', fallback=35)
        return tuple(sorted((low, high)))

    @invites_limit.setter
    def invites_limit(self, val):
        low, high = val
        self.save_val('inv_limit_low', str(low))
        self.save_val('inv_limit_high', str(high))

    @property
    def limit_reset(self):
        return self.config.getint(self.section, 'limit_reset', fallback=60)

    @limit_reset.setter
    def limit_reset(self, val):
        self.save_val('limit_reset', str(val))

    @property
    def skip_sign_in(self):
        return self.config.getboolean(self.section, 'skip_sign_in', fallback=False)

    @skip_sign_in.setter
    def skip_sign_in(self, val):
        val = 'yes' if val else 'no'
        self.save_val('skip_sign_in', val)

    @property
    def proxy(self):
        section = 'proxy'
        return {
            'proxy_type': self.config.get(section, 'type', fallback='http'),
            'addr': self.config.get(section, 'address'),
            'port': self.config.getint(section, 'port'),
            'username': self.config.get(section, 'username'),
            'password': self.config.get(section, 'password')
        }

    def get_detail_msg(self):
        return ('⚙  Settings\n\n'
                'Max last seen days: <code>{}</code>\n'
                'Join delay: <code>{}</code> seconds').format(self.last_seen_filter or 'Any', self.join_delay)

    def get_run_settings_msg(self):
        return ('Specify a range of invites one account cand send\n'
                'and how often they reset.\n\n'
                'Invites: <code>{}-{}</code>\n'
                'Reset after: <code>{}</code> days\n').format(*self.invites_limit, self.limit_reset)


settings = Settings()
