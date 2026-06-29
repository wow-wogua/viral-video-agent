from pydantic import BaseModel
import uuid

class AnalyzeRequest(BaseModel):
    query: str
    session_id: str = None
    platforms: list[str] = ["douyin", "bilibili"]

    def model_post_init(self, __context):
        if self.session_id is None:
            self.session_id = str(uuid.uuid4())

class AnalyzeResponse(BaseModel):
    session_id: str
    status: str
    report: str = ""
    plan: list[str] = []
    cost: dict = {}