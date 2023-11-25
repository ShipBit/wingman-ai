from services.printr import Printr
from services.check_version import LOCAL_VERSION

class Splashscreen:
    @staticmethod
    def get_pluralized_wingman(count=1):
        return f"Wingm{'a' if count == 1 else 'e'}n"

    @staticmethod
    def show(tower):
        discord_link = Printr.clr('https://discord.gg/JSNbYbyH', Printr.CYAN)
        github_link = Printr.clr('https://github.com/shipbit/wingman-ai', Printr.CYAN)
        patreon_link = Printr.clr('https://www.patreon.com/ShipBit', Printr.CYAN)

        version = LOCAL_VERSION
        wingmen = tower.get_wingmen()
        wingmen_count = len(wingmen)
        broken_wingmen = tower.get_broken_wingmen()
        broken_count = len(broken_wingmen)

        print("")
        print("{:^38} {:<80}".format(Printr.clr('', Printr.RED), Printr.clr('___       ______                                              _______________', Printr.BLUE)))
        print("{:^38} {:<80}".format(Printr.clr('/ \\          / \\', Printr.RED), Printr.clr('__ |     / /__(_)_____________ _______ _________ _______      ___    |___  _/', Printr.BLUE)))
        print("{:^38} {:<80}".format(Printr.clr('/   \\        /   \\', Printr.RED), Printr.clr('__ | /| / /__  /__  __ \\_  __ `/_  __ `__ \\  __ `/_  __ \\     __  /| |__  /', Printr.BLUE)))
        print("{:^38} {:<80}".format(Printr.clr('/     \\\\‾‾‾‾//     \\', Printr.RED), Printr.clr('__ |/ |/ / _  / _  / / /  /_/ /_  / / / / / /_/ /_  / / /     _  ___ |_/ /', Printr.BLUE)))
        print("{:^38} {:<80}".format(Printr.clr('/       \\\\  //       \\', Printr.RED), Printr.clr('____/|__/  /_/  /_/ /_/_\\__, / /_/ /_/ /_/\\__,_/ /_/ /_/      /_/  |_/___/', Printr.BLUE)))
        print("{:^38} {:<80}".format(Printr.clr('/_________\\\\//_________\\', Printr.RED), Printr.clr('                       /____/', Printr.BLUE)))
        print("{:^46} {:>82}".format(Printr.clr(f'\\{Printr.UNDERLINE}⎺⎺⎺⎺⎺⎺⎺⎺⎺⎺⎺⎺{Printr.END_UNDERLINE}/', Printr.RED), f"Version: {Printr.clr(version, Printr.RED)}"))
        print("{:^38} {:<10} {:<60}".format(Printr.clr('\\⎺⎺⎺⎺⎺⎺⎺⎺⎺⎺/', Printr.RED), 'Discord:', discord_link))
        print("{:^38} {:<10} {:<60}".format(Printr.clr('\\________/', Printr.RED), 'GitHub:', github_link))
        print("{:^38} {:<10} {:<60}".format(Printr.clr('', Printr.RED), 'Patreon:', patreon_link))
        print("")
        Printr.box_start()
        Printr.box_print(f"{Printr.BOLD}Welcome, Commander! {Printr.NORMAL_WEIGHT}{Printr.FAINT}o7{Printr.NORMAL_WEIGHT}")
        Printr.box_print("")
        Printr.box_print("")
        if wingmen_count > 0:
            Printr.box_print(f"You currently have {Printr.BLUE}{Printr.BOLD}{wingmen_count}{Printr.CLEAR} {Splashscreen.get_pluralized_wingman(wingmen_count)} registered:")
            Printr.box_print("")
            for wingman in wingmen:
                key = wingman.get_record_key()
                Printr.box_print(f" 〈{Printr.BLUE}{key:^9}{Printr.CLEAR}〉  {wingman.name}")
        else:
            Printr.box_print(f" {Printr.clr('⚠️ WARNING ⚠️', Printr.YELLOW)}")
            Printr.box_print("")
            Printr.box_print(" Seems like you don't have any functional wingmen registered.")
            Printr.box_print(f" Please check your {Printr.clr('config.yaml', Printr.BLUE)}")

        if broken_count > 0:
            Printr.box_print("")
            Printr.box_print("")
            Printr.box_print(f" {Printr.clr('⚠️ WARNING ⚠️', Printr.YELLOW)}")
            Printr.box_print("")
            Printr.box_print(f"Looks like {Printr.RED}{Printr.BOLD}{broken_count}{Printr.CLEAR} of your Wingmen {'is' if broken_count == 1 else 'are'} not operational:")
            Printr.box_print("")
            for wingman in broken_wingmen:
                Printr.box_print(f" 〈{Printr.RED}{wingman['name']:^20}{Printr.CLEAR}〉  {wingman['error']}")

        Printr.box_end()
        print("")
