from __future__ import annotations

import base64
import json
import http.client
import mimetypes
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator


if TYPE_CHECKING:
    from .config import Config


Message = dict[str, Any]
StreamDelta = dict[str, str]


class QwenError(RuntimeError):
    pass


@dataclass
class QwenClient:
    api_key: str
    base_url: str
    model: str
    timeout: int = 240

    @classmethod
    def from_config(cls, config: Config) -> QwenClient:
        return cls(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
        )

    def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        enable_thinking: bool | None = None,
        thinking_budget: int | None = None,
    ) -> str:
        if not self.api_key:
            raise QwenError("Missing API key. Set DASHSCOPE_API_KEY in .env or system environment.")
        if self._uses_dashscope_native_api():
            try:
                return self._complete_dashscope_native(
                    messages,
                    temperature=temperature,
                    enable_thinking=enable_thinking,
                    thinking_budget=thinking_budget,
                )
            except QwenError as exc:
                if "url error" not in str(exc).lower():
                    raise
                return self._compatible_client()._complete_openai_compatible(
                    messages,
                    temperature=temperature,
                    enable_thinking=enable_thinking,
                    thinking_budget=thinking_budget,
                )
        return self._complete_openai_compatible(
            messages,
            temperature=temperature,
            enable_thinking=enable_thinking,
            thinking_budget=thinking_budget,
        )

    def stream_complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        enable_thinking: bool | None = None,
        thinking_budget: int | None = None,
    ) -> Iterator[StreamDelta]:
        if not self.api_key:
            raise QwenError("Missing API key. Set DASHSCOPE_API_KEY in .env or system environment.")
        if self._uses_dashscope_native_api():
            yield from self._compatible_client()._stream_complete_openai_compatible(
                messages,
                temperature=temperature,
                enable_thinking=enable_thinking,
                thinking_budget=thinking_budget,
            )
            return
        yield from self._stream_complete_openai_compatible(
            messages,
            temperature=temperature,
            enable_thinking=enable_thinking,
            thinking_budget=thinking_budget,
        )

    def complete_with_images(
        self,
        image_paths: list[Path],
        prompt: str,
        *,
        temperature: float = 0.2,
        enable_thinking: bool | None = None,
        thinking_budget: int | None = None,
    ) -> str:
        messages: list[Message] = [
            {
                "role": "user",
                "content": [
                    *[_image_content_part(path) for path in image_paths],
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        client = self._compatible_client() if self._uses_dashscope_native_api() else self
        return client._complete_openai_compatible(
            messages,
            temperature=temperature,
            enable_thinking=enable_thinking,
            thinking_budget=thinking_budget,
        )

    def _compatible_client(self) -> QwenClient:
        fallback_base_url = self.base_url
        if self._uses_dashscope_native_api():
            fallback_base_url = self.base_url.replace("/api/v1", "/compatible-mode/v1", 1)
        return QwenClient(
            api_key=self.api_key,
            base_url=fallback_base_url,
            model=self.model,
            timeout=self.timeout,
        )

    def _uses_dashscope_native_api(self) -> bool:
        return "dashscope.aliyuncs.com/api/v1" in self.base_url and "compatible-mode" not in self.base_url

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(3):
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Connection": "close",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise QwenError(f"Qwen HTTP {exc.code}: {body}") from exc
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                break
        raise QwenError(f"Qwen connection failed: {last_error}") from last_error

    def _post_json_stream(self, url: str, payload: dict[str, Any]) -> Iterator[StreamDelta]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Connection": "close",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_line = line.removeprefix("data:").strip()
                    if data_line == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_line)
                    except json.JSONDecodeError:
                        continue
                    delta = self._extract_stream_delta(chunk)
                    if delta:
                        yield delta
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise QwenError(f"Qwen HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError) as exc:
            raise QwenError(f"Qwen stream connection failed: {exc}") from exc

    def _complete_dashscope_native(
        self,
        messages: list[Message],
        *,
        temperature: float,
        enable_thinking: bool | None,
        thinking_budget: int | None,
    ) -> str:
        url = f"{self.base_url}/services/aigc/text-generation/generation"
        parameters: dict[str, Any] = {
            "result_format": "message",
            "temperature": temperature,
        }
        if enable_thinking is not None:
            parameters["enable_thinking"] = enable_thinking
        if thinking_budget is not None:
            parameters["thinking_budget"] = int(thinking_budget)
        payload = {
            "model": self.model,
            "input": {"messages": messages},
            "parameters": parameters,
        }
        result = self._post_json(url, payload)
        try:
            return result["output"]["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise QwenError(f"Unexpected DashScope response: {result}") from exc

    def _complete_openai_compatible(
        self,
        messages: list[Message],
        *,
        temperature: float,
        enable_thinking: bool | None,
        thinking_budget: int | None,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if enable_thinking is not None:
            payload["enable_thinking"] = enable_thinking
        if thinking_budget is not None:
            payload["thinking_budget"] = int(thinking_budget)
        result = self._post_json(url, payload)
        try:
            return result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise QwenError(f"Unexpected OpenAI-compatible response: {result}") from exc

    def _stream_complete_openai_compatible(
        self,
        messages: list[Message],
        *,
        temperature: float,
        enable_thinking: bool | None,
        thinking_budget: int | None,
    ) -> Iterator[StreamDelta]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if enable_thinking is not None:
            payload["enable_thinking"] = enable_thinking
        if thinking_budget is not None:
            payload["thinking_budget"] = int(thinking_budget)
        yield from self._post_json_stream(url, payload)

    @staticmethod
    def _extract_stream_delta(chunk: dict[str, Any]) -> StreamDelta:
        try:
            delta = chunk["choices"][0].get("delta") or {}
            content = delta.get("content")
            reasoning = delta.get("reasoning_content")
            if not isinstance(reasoning, str):
                reasoning = delta.get("reasoning")
            result: StreamDelta = {}
            if isinstance(content, str):
                result["content"] = content
            if isinstance(reasoning, str):
                result["reasoning"] = reasoning
            return result
        except (KeyError, IndexError, TypeError, AttributeError):
            return {}


def _image_content_part(path: Path) -> dict[str, Any]:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{data}"}}
