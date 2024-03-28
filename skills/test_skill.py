class TestSkill:
    def __init__(self) -> None:
        pass

    def action_one(self) -> None:
        print('action one')

    def action_two(self) -> bool:
        print('action two')
        return False

    def action_three(self, param_one, param_two = 'default') -> bool:
        print(f'action three with [param_one = {param_one}] and [param_two = {param_two}]')
        return True

    def action_four(self, param_one, param_two = 'default') -> bool:
        print(f'action four with [param_one = {param_one}] and [param_two = {param_two}]')
        return True

    def event_one(self) -> None:
        # @TODO: are events defined here? 🤔
        pass

    def event_two(self) -> int:
        # @TODO: are events defined here? 🤔
        return 42
