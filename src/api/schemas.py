from pydantic import BaseModel, Field
import uuid

class AnalyzeRequest(BaseModel):
    query: str
    session_id: str = None
    platforms: list[str] = Field(default_factory=lambda: ["douyin", "bilibili"])

    def model_post_init(self, __context):
        if self.session_id is None:
            self.session_id = str(uuid.uuid4())

class AnalyzeResponse(BaseModel):
    session_id: str
    status: str
    report: str = ""
    plan: list[str] = Field(default_factory=list)
    cost: dict = Field(default_factory=dict)
