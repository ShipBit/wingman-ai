from typing_extensions import TypedDict
from pydantic import BaseModel


class ContextInfo(BaseModel):
    contexts: list[str]
    currentContext: str


class SystemCore(TypedDict):
    version: str
    latest: str
    isLatest: bool


class SystemInfo(BaseModel):
    os: str
    core: SystemCore
