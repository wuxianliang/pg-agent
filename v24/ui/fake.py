"""Scripted, socket-free DeepSeek adapter for M1 acceptance."""
from __future__ import annotations
import json
from v24.host.deepseek import DeepSeekAdapter, AdapterFailure

class ScriptedUiAdapter(DeepSeekAdapter):
    def __init__(self, outcomes):
        super().__init__(api_key="v24-scripted", timeout_s=30, transport=self)
        self.outcomes = list(outcomes); self.calls = []
    def post(self, url, body, headers, deadline):
        self.calls.append(body); return 200, b"{}"
    def send(self, prepared): return self.post("", prepared.body, {}, 0)[0], b"{}", 1
    def interpret(self, prepared, status, raw, wall_ms):
        if not self.outcomes: raise AdapterFailure("script_exhausted")
        outcome = self.outcomes.pop(0)
        kind = outcome.get("kind", "final")
        usage = outcome.get("usage", {"tokens": 5, "wall_ms": wall_ms})
        if kind == "final":
            text = outcome.get("text", "done")
            return {"class":"success","result":{"final":{"text":text},"usage":usage},"reply":None,
                    "assistant_message":{"role":"assistant","content":text,"reasoning_content":"scripted"},"tool_calls":None,"reason":None}
        if kind == "tool":
            key, args = outcome["key"], outcome.get("args", {})
            ident = outcome.get("id", "call_1")
            arguments = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
            assistant = {"role":"assistant","content":None,"reasoning_content":"scripted",
                         "tool_calls":[{"id":ident,"type":"function","name":key,"arguments":arguments}]}
            return {"class":"success","result":{"tool_calls":[{"key":key,"args":args}],"usage":usage},"reply":None,
                    "assistant_message":assistant,"tool_calls":[{"provider_id":ident,"provider_name":key,"key":key,"args":args,"arguments":arguments}],"reason":None}
        if kind == "interaction":
            payload = outcome.get("payload", {"prompt":"Continue?"})
            return {"class":"success","result":{"interaction":{"schema_digest":"0"*64,"prompt_digest":"1"*64,"payload":payload},"usage":usage},"reply":None,"assistant_message":None,"tool_calls":None,"reason":None}
        raise AdapterFailure("script_invalid")
