from __future__ import annotations

import abc
import uuid

import httpx


class AgentClient(abc.ABC):
    @abc.abstractmethod
    async def send_task(self, prompt: str) -> str:
        """Send a task prompt to the agent and return its final text output."""
        ...


class SimpleHTTPAgentClient(AgentClient):
    """Sends a prompt via HTTP POST and returns the response text.

    Expects the agent to accept ``{"prompt": "..."}`` and return
    ``{"response": "..."}``.
    """

    def __init__(self, agent_url: str, timeout: float = 120.0) -> None:
        self.agent_url = agent_url
        self.timeout = timeout

    async def send_task(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.agent_url, json={"prompt": prompt})
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", data.get("output", data.get("text", str(data))))


class A2AAgentClient(AgentClient):
    """Sends a task via the A2A protocol and returns the agent's text output."""

    def __init__(self, agent_url: str, timeout: float = 120.0) -> None:
        self.agent_url = agent_url
        self.timeout = timeout

    async def send_task(self, prompt: str) -> str:
        from a2a.client import create_client
        from a2a.types import Message, Part, Role, SendMessageRequest

        client = await create_client(self.agent_url)
        try:
            request = SendMessageRequest(
                message=Message(
                    role=Role.ROLE_USER,
                    message_id=uuid.uuid4().hex,
                    parts=[Part(text=prompt)],
                ),
            )

            result_text = ""
            async for event in client.send_message(request):
                payload_type = event.WhichOneof("payload")
                if payload_type == "message":
                    for part in event.message.parts:
                        if part.text:
                            result_text += part.text
                elif payload_type == "task":
                    for artifact in event.task.artifacts:
                        for part in artifact.parts:
                            if part.text:
                                result_text += part.text
                elif payload_type == "artifact_update":
                    for part in event.artifact_update.artifact.parts:
                        if part.text:
                            result_text = part.text

            return result_text
        finally:
            await client.close()
