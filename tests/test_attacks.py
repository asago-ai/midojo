import pytest

from midojo.attacks import (
    ASI_DESCRIPTIONS,
    DEFAULT_LIBRARY,
    ASICategory,
    AttackLibrary,
    AttackTechnique,
    parse_asi_category,
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
        assert technique.source == "agentdojo:important_instructions"
        assert technique.license == "MIT"


class TestAttackLibrary:
    def test_duplicate_registration_raises(self):
        lib = AttackLibrary([AttackTechnique(id="v", wrapper=lambda p: p, description="x")])
        with pytest.raises(ValueError, match="already registered"):
            lib.register(AttackTechnique(id="v", wrapper=lambda p: p, description="y"))


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
