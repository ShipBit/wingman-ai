class SkillManager:
    _initialized_skills = []

    def __init__(self) -> None:
        pass

    def load_skill(self, skill: str) -> bool:
        if skill in self._initialized_skills:
            # @TODO: Reload?
            return True

        return True


    # @TODO: needed?
    # def configure_skill
    # def delete_skill_config
