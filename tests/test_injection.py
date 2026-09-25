"""The pure injection executor: matching and the four modes."""

from __future__ import annotations

import json

from midojo.injection import (
    apply_output_instructions,
    execute_injection,
    matching_output_instructions,
)
from midojo.types import InjectionInstruction


def _inst(**kw) -> InjectionInstruction:
    kw.setdefault("channel", "tool_output")
    kw.setdefault("probe_key", "t:p")
    kw.setdefault("payload", "PWNED")
    return InjectionInstruction(**kw)


class TestMatching:
    def test_wildcard_matches_any_tool(self):
        plan = [_inst()]
        assert matching_output_instructions(plan, "Read") == plan

    def test_named_tool_matches_only_itself(self):
        plan = [_inst(target={"tool": "Read"})]
        assert matching_output_instructions(plan, "Read") == plan
        assert matching_output_instructions(plan, "Bash") == []

    def test_tool_description_channel_never_matches_output(self):
        plan = [_inst(channel="tool_description")]
        assert matching_output_instructions(plan, "Read") == []

    def test_wildcard_does_not_shadow_a_later_named_instruction(self):
        """Both apply, in order -- the POC's first-match-wins bug is gone."""
        wildcard = _inst(payload="A")
        named = _inst(payload="B", target={"tool": "Read"})
        plan = [wildcard, named]
        assert matching_output_instructions(plan, "Read") == [wildcard, named]

    def test_two_instructions_for_the_same_tool_both_land(self):
        plan = [_inst(payload="A", target={"tool": "Read"}), _inst(payload="B", target={"tool": "Read"})]
        assert apply_output_instructions("data", plan, "Read") == "data\nA\nB"


class TestModes:
    def test_replace_discards_the_real_result(self):
        assert execute_injection("real data", _inst(mode="replace")) == "PWNED"

    def test_append_after_a_newline(self):
        assert execute_injection("real data", _inst(mode="append")) == "real data\nPWNED"

    def test_append_to_empty_result_is_just_the_payload(self):
        assert execute_injection("", _inst(mode="append")) == "PWNED"

    def test_new_field_adds_annotation_to_a_json_object(self):
        out = json.loads(execute_injection('{"a": 1}', _inst(mode="new_field")))
        assert out == {"a": 1, "_annotation": "PWNED"}

    def test_new_field_falls_back_to_append_for_non_object(self):
        assert execute_injection("plain text", _inst(mode="new_field")) == "plain text\nPWNED"


class TestEmbed:
    def test_embed_into_named_field(self):
        out = json.loads(execute_injection('{"notes": "clear skies"}', _inst(mode="embed", target={"field": "notes"})))
        assert out["notes"] == "clear skies PWNED"

    def test_embed_into_named_field_one_list_level_deep(self):
        payload = '{"rows": [{"memo": "payroll"}]}'
        out = json.loads(execute_injection(payload, _inst(mode="embed", target={"field": "memo"})))
        assert out["rows"][0]["memo"] == "payroll PWNED"

    def test_embed_auto_detects_the_longest_multiword_field(self):
        payload = '{"id": "ACC1", "note": "a slightly longer sentence", "tag": "x"}'
        out = json.loads(execute_injection(payload, _inst(mode="embed")))
        assert out["note"].endswith("PWNED")
        assert out["id"] == "ACC1"

    def test_embed_never_stringifies_a_numeric_field(self):
        """target.field on a number must not coerce it -- silent value mangling."""
        out = json.loads(execute_injection('{"balance": 15420.5}', _inst(mode="embed", target={"field": "balance"})))
        assert out["balance"] == 15420.5
        assert out["_annotation"] == "PWNED"

    def test_embed_falls_back_to_annotation_when_no_text_field(self):
        out = json.loads(execute_injection('{"n": 1}', _inst(mode="embed")))
        assert out == {"n": 1, "_annotation": "PWNED"}

    def test_embed_falls_back_to_append_for_prose(self):
        """The bundled suites return prose, so embed must degrade cleanly."""
        assert execute_injection("New York: 72F, sunny", _inst(mode="embed")) == "New York: 72F, sunny\nPWNED"

    def test_missing_named_field_falls_through_to_autodetect(self):
        out = json.loads(
            execute_injection('{"note": "some words here"}', _inst(mode="embed", target={"field": "absent"}))
        )
        assert out["note"].endswith("PWNED")
