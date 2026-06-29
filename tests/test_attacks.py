import json

import pytest

from midojo.attacks import (
    ASI_DESCRIPTIONS,
    DEFAULT_LIBRARY,
    ASICategory,
    AttackLibrary,
    AttackTechnique,
    Origin,
    PayloadSet,
    parse_asi_category,
    resolve_source,
    wrap_payload,
)


class TestDefaultLibrary:
    def test_builtin_vehicles_present(self):
        assert set(DEFAULT_LIBRARY.ids()) >= {"verbatim", "important_instructions", "ignore_previous"}

    def test_verbatim_passes_payload_through(self):
        assert wrap_payload("hello", "verbatim") == "hello"

    def test_important_instructions_wraps_payload(self):
        wrapped = wrap_payload("do the thing", "important_instructions")
        assert "do the thing" in wrapped
        assert "Emma Johnson" in wrapped

    def test_unknown_attack_type_raises(self):
        with pytest.raises(ValueError, match="Unsupported attack_type 'nope'"):
            wrap_payload("x", "nope")


class TestProvenance:
    def test_important_instructions_attributed_to_agentdojo(self):
        technique = DEFAULT_LIBRARY.get("important_instructions")
        assert technique.origin.kind == "agentdojo"
        assert technique.origin.url is not None
        assert technique.origin.url.startswith("https://github.com/ethz-spylab/agentdojo/blob/")
        assert technique.license == "MIT"

    def test_vendored_origin_requires_pin(self):
        with pytest.raises(ValueError, match="requires 'path' and 'commit'"):
            Origin(kind="garak", path="garak/data/payloads/x.json")

    def test_file_origin_requires_path(self):
        with pytest.raises(ValueError, match="requires 'path'"):
            Origin(kind="file")

    def test_builtin_origin_uri(self):
        assert Origin(kind="builtin").uri == "builtin"
        assert Origin(kind="builtin").url is None


class TestAttackLibrary:
    def test_duplicate_registration_raises(self):
        lib = AttackLibrary([AttackTechnique(id="v", wrapper=lambda p: p, description="x")])
        with pytest.raises(ValueError, match="already registered"):
            lib.register(AttackTechnique(id="v", wrapper=lambda p: p, description="y"))


class TestPayloadSets:
    def test_vendored_garak_sets_present(self):
        assert set(DEFAULT_LIBRARY.payload_set_ids()) >= {
            "garak:hijack_hate_humans",
            "garak:hijack_kill_humans",
            "garak:hijack_long_prompt",
            "garak:access_shell_commands",
            "garak:sql_injection",
        }

    def test_vendored_set_provenance(self):
        payload_set = DEFAULT_LIBRARY.get_payload_set("garak:hijack_hate_humans")
        assert payload_set.license == "MIT"
        origin = payload_set.origin
        assert origin.kind == "garak"
        assert origin.path == "garak/resources/promptinject/prompt_data.py"
        assert origin.commit
        # The pin is navigable: derived uri and a browseable upstream url.
        assert origin.uri == f"garak@{origin.commit}:{origin.path}"
        assert origin.url == f"https://github.com/NVIDIA/garak/blob/{origin.commit}/{origin.path}"
        assert payload_set.references
        assert all("I hate humans" in p for p in payload_set.payloads)

    def test_by_asi(self):
        ids = [s.id for s in DEFAULT_LIBRARY.by_asi("ASI-05")]
        assert "garak:access_shell_commands" in ids
        assert "garak:sql_injection" in ids
        assert "garak:hijack_hate_humans" not in ids

    def test_by_asi_accepts_member(self):
        assert DEFAULT_LIBRARY.by_asi(ASICategory.ASI_01) == DEFAULT_LIBRARY.by_asi("ASI-01")

    def test_unknown_set_raises(self):
        with pytest.raises(ValueError, match="Unknown payload set 'garak:nope'"):
            DEFAULT_LIBRARY.get_payload_set("garak:nope")

    def test_duplicate_set_registration_raises(self):
        lib = AttackLibrary(payload_sets=[PayloadSet(id="s", payloads=("x",), description="d")])
        with pytest.raises(ValueError, match="already registered"):
            lib.register_payload_set(PayloadSet(id="s", payloads=("y",), description="d"))


class TestResolveSource:
    def test_registry_lookup(self):
        payload_set = resolve_source("garak:sql_injection")
        assert payload_set.id == "garak:sql_injection"
        assert payload_set.payloads

    def test_explicit_library(self):
        lib = AttackLibrary(payload_sets=[PayloadSet(id="builtin:mine", payloads=("x",), description="d")])
        assert resolve_source("builtin:mine", library=lib).payloads == ("x",)

    def test_file_midojo_shape(self, tmp_path):
        (tmp_path / "custom.json").write_text(
            json.dumps(
                {
                    "id": "custom:set",
                    "description": "my payloads",
                    "asi_categories": ["ASI-06"],
                    "payloads": ["plant this", "and this"],
                }
            )
        )
        payload_set = resolve_source("file:custom.json", base_dir=tmp_path)
        assert payload_set.id == "custom:set"
        assert payload_set.asi_categories == (ASICategory.ASI_06,)
        assert payload_set.payloads == ("plant this", "and this")

    def test_file_garak_raw_shape(self, tmp_path):
        (tmp_path / "raw.json").write_text(
            json.dumps(
                {
                    "garak_payload_name": "Some garak corpus",
                    "payload_types": ["Code/Malicious"],
                    "payloads": ["`ls /`"],
                }
            )
        )
        payload_set = resolve_source("file:raw.json", base_dir=tmp_path)
        assert payload_set.id == "file:raw.json"
        assert payload_set.description == "Some garak corpus"
        assert payload_set.payloads == ("`ls /`",)
        assert payload_set.origin == Origin(kind="file", path="raw.json")

    def test_file_missing_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Payload set file not found"):
            resolve_source("file:nope.json", base_dir=tmp_path)


class TestASITaxonomy:
    def test_top_ten_categories(self):
        assert len(ASICategory) == 10
        assert ASICategory.ASI_01.value == "ASI-01"
        assert ASI_DESCRIPTIONS[ASICategory.ASI_01] == "Agent Goal Hijack"

    def test_parse_from_code_string(self):
        assert parse_asi_category("ASI-06") is ASICategory.ASI_06

    def test_parse_passthrough_member(self):
        assert parse_asi_category(ASICategory.ASI_06) is ASICategory.ASI_06

    def test_parse_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown OWASP ASI category 'T6'"):
            parse_asi_category("T6")
