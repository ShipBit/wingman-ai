from services.printr import Printr
from services.check_version import LOCAL_VERSION

class Splashscreen:
    @staticmethod
    def show(tower):
        discord_link = Printr.clr('https://discord.gg/JSNbYbyH', Printr.CYAN)
        github_link = Printr.clr('https://github.com/shipbit/wingman-ai', Printr.CYAN)
        patreon_link = Printr.clr('https://www.patreon.com/ShipBit', Printr.CYAN)

        version = LOCAL_VERSION
        wingmen = tower.get_wingmen()
        count = len(wingmen)
        ea = 'e' if count > 1 else 'a'

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
        if count > 0:
            Printr.box_print(f"You currently have {Printr.BLUE}{Printr.BOLD}{count}{Printr.CLEAR} Wingm{ea}n registered:")
            Printr.box_print("")
            for wingman in wingmen:
                key = wingman.get_record_key()
                Printr.box_print(f" 〈{Printr.BLUE}{key:^9}{Printr.CLEAR}〉  {wingman.name}")
        else:
            Printr.box_print(f" {Printr.clr('⚠️ WARNING ⚠️', Printr.YELLOW)}")
            Printr.box_print("")
            Printr.box_print(" Seems like you don't have any wingmen registered.")
            Printr.box_print(f" Please check your {Printr.clr('config.yaml', Printr.BLUE)}")
        Printr.box_end()
        print("")
