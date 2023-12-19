import requests
from packaging import version
from services.printr import Printr

LOCAL_VERSION = "1.1.3b1"
VERSION_ENDPOINT = "https://shipbit.de/wingman.json"

printr = Printr()


class VersionCheck:
    _instance = None

    # NOTE this is a singleton class
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VersionCheck, cls).__new__(cls)

            cls.latest_version = version.parse("0.0.0")
            cls.local_version = version.parse(LOCAL_VERSION)
            cls._instance.check_version()
            return cls._instance

    def check_version(self):
        try:
            app_version = self.local_version

            response = requests.get(VERSION_ENDPOINT, timeout=10)
            response.raise_for_status()

            remote_version_str = response.json().get("version", None)
            remote_version = version.parse(remote_version_str)

            self.latest_version = remote_version

            return app_version >= remote_version

        except requests.RequestException:
            # msg = str(e)
            msg = "Could not reach version endpoint."
            printr.print_warn(f"Error fetching version information: \n{msg}")
            # printr.print_warn(f"Error fetching version information: \n{e}")
            return False
        except ValueError as e:
            printr.print_warn(f"Error with version information: {e}")
            return False

    def current_version_is_latest(self):
        return self.local_version >= self.latest_version

    def get_local_version(self, as_string=True) -> str | version.Version:
        return LOCAL_VERSION if as_string else self.local_version

    def get_latest_version(self, as_string=True) -> str | version.Version:
        return str(self.latest_version) if as_string else self.latest_version
