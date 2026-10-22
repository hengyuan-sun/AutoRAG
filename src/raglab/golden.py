"""黄金集条目和证据范围的共享输入契约。"""
from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=1, max_length=128)
    block_id: str = Field(min_length=1, max_length=128)
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_range(self):
        if self.start >= self.end:
            raise ValueError("证据范围必须满足start < end")
        return self


class GoldenItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=10000)
    relevant_documents: list[str] = Field(min_length=1, max_length=500)
    evidence: list[EvidenceSpan] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def valid_query(self):
        if not self.query.strip():
            raise ValueError("问题不能为空")
        if len(set(self.relevant_documents)) != len(self.relevant_documents):
            raise ValueError("相关文档不能重复")
        return self
