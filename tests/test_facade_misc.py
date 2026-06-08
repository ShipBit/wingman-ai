"""Run: PYTHONPATH=. venv/bin/python -m tests.test_facade_misc"""
import asyncio
from wingmen.facade import SkillConversation, SkillSecrets, SkillSkills, SkillSettings, FacadeError


class _Conv:
    def __init__(self): self.messages = [{"role": "user", "content": "hi"}]; self.asst = []
    async def add_assistant_message(self, c): self.asst.append(c)


class _Cond: summary = "the summary"


class _SM:
    skills = [type("S", (), {"name": "Timer", "config": type("C", (), {"display_name": "Timer"})()})()]


class _Audio: output = "out"; input = "in"


class _Settings: audio = _Audio()


class _W:
    def __init__(self):
        self.conversation = _Conv(); self.condenser = _Cond()
        self.skill_manager = _SM(); self.settings = _Settings()
        self.added_user = None
    async def add_user_message(self, c): self.added_user = c
    async def reset_conversation_history(self): self.conversation.messages = []
    async def retrieve_secret(self, name, errors, is_required=True): return f"secret:{name}"


def test_conversation():
    w = _W(); c = SkillConversation(w)
    assert c.history() == [{"role": "user", "content": "hi"}]
    assert c.summary == "the summary"
    asyncio.get_event_loop().run_until_complete(c.add_user("yo"))
    assert w.added_user == "yo"
    asyncio.get_event_loop().run_until_complete(c.add_assistant("ok"))
    assert w.conversation.asst == ["ok"]
    print("PASS: conversation")


def test_secrets_and_skills_and_settings():
    w = _W()
    s = SkillSecrets(w)
    assert asyncio.get_event_loop().run_until_complete(s.retrieve("API")) == "secret:API"
    sk = SkillSkills(w)
    active = sk.active()
    assert active[0]["name"] == "Timer"
    assert sk.has("Timer") and not sk.has("Nope")
    st = SkillSettings(w)
    assert st.output_device == "out" and st.input_device == "in"
    try:
        st.audio = 1
        raised = False
    except FacadeError:
        raised = True
    assert raised, "settings write must raise FacadeError"
    print("PASS: secrets/skills/settings")


if __name__ == "__main__":
    test_conversation()
    test_secrets_and_skills_and_settings()
    print("ALL OK")
