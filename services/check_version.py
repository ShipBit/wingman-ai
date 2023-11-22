import requests
from packaging import version
from services.printr import Printr

LOCAL_VERSION = '1.0.0a2'


def check_version(url):
    try:
        app_version = version.parse(LOCAL_VERSION)

        response = requests.get(url, timeout=10)
        response.raise_for_status()

        remote_version_str = response.json().get("version", None)
        remote_version = version.parse(remote_version_str)

        # print(f"{Printr.clr('⚙︎ WingmanAI version:', Printr.GREEN)} {app_version}")
        if app_version < remote_version:
            print(
                f"{Printr.clr('⚙︎ A newer WingmanAI version is available:', Printr.YELLOW)} {remote_version}"
            )

    except requests.RequestException as e:
        Printr.err_print(f"Error fetching version information: {e}")
    except ValueError as e:
        Printr.err_print(f"Error with version information: {e}")
    except FileNotFoundError as e:
        Printr.err_print(f"Error: The local version file was not found: {e}")
