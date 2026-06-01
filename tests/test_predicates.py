import pytest
from pydantic import BaseModel

from midojo.predicates import (
    AllOf,
    AnyOf,
    Not,
    evaluate_predicate,
    parse_predicate,
)
from midojo.providers.builtin import (
    EnvFieldContains,
    EnvFieldEquals,
    EnvFieldUnchanged,
    EnvListAnyMatch,
    EnvListCount,
    OutputContains,
    OutputContainsAll,
    OutputContainsAny,
)
from midojo.types import Environment


class EmptyEnv(Environment):
    pass


class CountEnv(Environment):
    count: int = 0


class MessageEnv(Environment):
    message: str = ""


class Alert(BaseModel):
    city: str
    message: str


class AlertsEnv(Environment):
    weather_alerts: list[Alert] = []


class ItemsEnv(Environment):
    items: list = []


class BalanceEnv(Environment):
    balance: int = 0


class StatusItemsEnv(Environment):
    status: str = ""
    items: list = []


class CityCondition(BaseModel):
    condition: str


class CitiesEnv(Environment):
    cities: dict[str, CityCondition] = {}


EMPTY_ENV = EmptyEnv()


class TestOutputContains:
    def test_match(self):
        p = OutputContains(value="sunny")
        assert evaluate_predicate(p, "It is sunny today", EMPTY_ENV, EMPTY_ENV)

    def test_case_insensitive(self):
        p = OutputContains(value="SUNNY")
        assert evaluate_predicate(p, "it is sunny today", EMPTY_ENV, EMPTY_ENV)

    def test_no_match(self):
        p = OutputContains(value="rainy")
        assert not evaluate_predicate(p, "It is sunny today", EMPTY_ENV, EMPTY_ENV)


class TestOutputContainsAll:
    def test_all_present(self):
        p = OutputContainsAll(values=["72", "sunny"])
        assert evaluate_predicate(p, "The weather is 72°F and sunny.", EMPTY_ENV, EMPTY_ENV)

    def test_one_missing(self):
        p = OutputContainsAll(values=["72", "rainy"])
        assert not evaluate_predicate(p, "The weather is 72°F and sunny.", EMPTY_ENV, EMPTY_ENV)

    def test_case_insensitive(self):
        p = OutputContainsAll(values=["NEW YORK", "72"])
        assert evaluate_predicate(p, "New York is 72°F", EMPTY_ENV, EMPTY_ENV)


class TestOutputContainsAny:
    def test_one_present(self):
        p = OutputContainsAny(values=["rainy", "sunny"])
        assert evaluate_predicate(p, "It is sunny today", EMPTY_ENV, EMPTY_ENV)

    def test_none_present(self):
        p = OutputContainsAny(values=["rainy", "cloudy"])
        assert not evaluate_predicate(p, "It is sunny today", EMPTY_ENV, EMPTY_ENV)


class TestEnvFieldEquals:
    def test_match(self):
        p = EnvFieldEquals(field="count", value=5)
        assert evaluate_predicate(p, "", EMPTY_ENV, CountEnv(count=5))

    def test_mismatch(self):
        p = EnvFieldEquals(field="count", value=5)
        assert not evaluate_predicate(p, "", EMPTY_ENV, CountEnv(count=3))

    def test_dotted_path(self):
        p = EnvFieldEquals(field="cities.New York.condition", value="sunny")
        env = CitiesEnv(cities={"New York": CityCondition(condition="sunny")})
        assert evaluate_predicate(p, "", EMPTY_ENV, env)


class TestEnvFieldContains:
    def test_substring_match(self):
        p = EnvFieldContains(field="message", value="tornado")
        assert evaluate_predicate(p, "", EMPTY_ENV, MessageEnv(message="Severe tornado warning"))

    def test_case_insensitive(self):
        p = EnvFieldContains(field="message", value="TORNADO")
        assert evaluate_predicate(p, "", EMPTY_ENV, MessageEnv(message="severe tornado warning"))

    def test_no_match(self):
        p = EnvFieldContains(field="message", value="earthquake")
        assert not evaluate_predicate(p, "", EMPTY_ENV, MessageEnv(message="tornado warning"))


class TestEnvListAnyMatch:
    def test_match(self):
        p = EnvListAnyMatch(field="weather_alerts", match={"city": "chicago", "message": "tornado"})
        env = AlertsEnv(weather_alerts=[Alert(city="Chicago", message="Severe tornado warning")])
        assert evaluate_predicate(p, "", EMPTY_ENV, env)

    def test_no_match(self):
        p = EnvListAnyMatch(field="weather_alerts", match={"city": "chicago", "message": "tornado"})
        env = AlertsEnv(weather_alerts=[Alert(city="New York", message="Heat advisory")])
        assert not evaluate_predicate(p, "", EMPTY_ENV, env)

    def test_empty_list(self):
        p = EnvListAnyMatch(field="weather_alerts", match={"city": "chicago"})
        env = AlertsEnv(weather_alerts=[])
        assert not evaluate_predicate(p, "", EMPTY_ENV, env)

    def test_partial_match_fails(self):
        p = EnvListAnyMatch(field="weather_alerts", match={"city": "chicago", "message": "tornado"})
        env = AlertsEnv(weather_alerts=[Alert(city="Chicago", message="Heat advisory")])
        assert not evaluate_predicate(p, "", EMPTY_ENV, env)


class TestEnvListCount:
    def test_correct_count(self):
        p = EnvListCount(field="items", count=3)
        assert evaluate_predicate(p, "", EMPTY_ENV, ItemsEnv(items=[1, 2, 3]))

    def test_wrong_count(self):
        p = EnvListCount(field="items", count=3)
        assert not evaluate_predicate(p, "", EMPTY_ENV, ItemsEnv(items=[1, 2]))

    def test_zero_count(self):
        p = EnvListCount(field="items", count=0)
        assert evaluate_predicate(p, "", EMPTY_ENV, ItemsEnv(items=[]))


class TestEnvFieldUnchanged:
    def test_unchanged(self):
        p = EnvFieldUnchanged(field="balance")
        assert evaluate_predicate(p, "", BalanceEnv(balance=100), BalanceEnv(balance=100))

    def test_changed(self):
        p = EnvFieldUnchanged(field="balance")
        assert not evaluate_predicate(p, "", BalanceEnv(balance=100), BalanceEnv(balance=50))


class TestAllOf:
    def test_all_true(self):
        p = AllOf(predicates=[OutputContains(value="72"), OutputContains(value="sunny")])
        assert evaluate_predicate(p, "72°F and sunny", EMPTY_ENV, EMPTY_ENV)

    def test_one_false(self):
        p = AllOf(predicates=[OutputContains(value="72"), OutputContains(value="rainy")])
        assert not evaluate_predicate(p, "72°F and sunny", EMPTY_ENV, EMPTY_ENV)


class TestAnyOf:
    def test_one_true(self):
        p = AnyOf(predicates=[OutputContains(value="rainy"), OutputContains(value="sunny")])
        assert evaluate_predicate(p, "72°F and sunny", EMPTY_ENV, EMPTY_ENV)

    def test_none_true(self):
        p = AnyOf(predicates=[OutputContains(value="rainy"), OutputContains(value="cloudy")])
        assert not evaluate_predicate(p, "72°F and sunny", EMPTY_ENV, EMPTY_ENV)


class TestNot:
    def test_negation(self):
        p = Not(predicate=OutputContains(value="rainy"))
        assert evaluate_predicate(p, "It is sunny", EMPTY_ENV, EMPTY_ENV)

    def test_double_negation(self):
        p = Not(predicate=Not(predicate=OutputContains(value="sunny")))
        assert evaluate_predicate(p, "It is sunny", EMPTY_ENV, EMPTY_ENV)


class TestNestedCombinators:
    def test_all_of_containing_not(self):
        p = AllOf(
            predicates=[
                OutputContains(value="sunny"),
                Not(predicate=OutputContains(value="rainy")),
            ]
        )
        assert evaluate_predicate(p, "It is sunny today", EMPTY_ENV, EMPTY_ENV)

    def test_any_of_with_env_checks(self):
        p = AnyOf(
            predicates=[
                EnvFieldEquals(field="status", value="active"),
                EnvListCount(field="items", count=0),
            ]
        )
        assert evaluate_predicate(p, "", EMPTY_ENV, StatusItemsEnv(status="inactive", items=[]))


class TestParsePredicate:
    def test_output_contains(self):
        p = parse_predicate({"output_contains": "sunny"})
        assert isinstance(p, OutputContains)
        assert p.value == "sunny"

    def test_output_contains_all(self):
        p = parse_predicate({"output_contains_all": ["72", "sunny"]})
        assert isinstance(p, OutputContainsAll)
        assert p.values == ["72", "sunny"]

    def test_env_list_any_match(self):
        p = parse_predicate({"env_list_any_match": {"field": "alerts", "match": {"city": "chicago"}}})
        assert isinstance(p, EnvListAnyMatch)
        assert p.field == "alerts"
        assert p.match == {"city": "chicago"}

    def test_env_field_unchanged_string(self):
        p = parse_predicate({"env_field_unchanged": "balance"})
        assert isinstance(p, EnvFieldUnchanged)
        assert p.field == "balance"

    def test_env_field_unchanged_dict(self):
        p = parse_predicate({"env_field_unchanged": {"field": "balance"}})
        assert isinstance(p, EnvFieldUnchanged)
        assert p.field == "balance"

    def test_all_of(self):
        p = parse_predicate({"all_of": [{"output_contains": "a"}, {"output_contains": "b"}]})
        assert isinstance(p, AllOf)
        assert len(p.predicates) == 2

    def test_not(self):
        p = parse_predicate({"not": {"output_contains": "bad"}})
        assert isinstance(p, Not)
        assert isinstance(p.predicate, OutputContains)

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown predicate type"):
            parse_predicate({"bogus": "value"})

    def test_multiple_keys_raises(self):
        with pytest.raises(ValueError, match="exactly one key"):
            parse_predicate({"output_contains": "a", "output_contains_all": ["b"]})

    def test_empty_dict_raises(self):
        with pytest.raises(ValueError, match="exactly one key"):
            parse_predicate({})
