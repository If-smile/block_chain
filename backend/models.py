from pydantic import BaseModel
from typing import Optional

class SessionConfig(BaseModel):
    nodeCount: int
    faultyNodes: int
    robotNodes: int  # 机器人节点数量
    topology: str
    branchCount: Optional[int] = 2
    proposalValue: int
    proposalContent: Optional[str] = ""
    maliciousProposer: bool
    allowTampering: bool
    messageDeliveryRate: int = 100

class SessionInfo(BaseModel):
    sessionId: str
    nodeCount: int
    faultyNodes: int
    topology: str
    proposalValue: int
    status: str
    createdAt: str
