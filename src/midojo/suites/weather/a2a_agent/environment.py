from agentdojo.functions_runtime import TaskEnvironment
from pydantic import BaseModel


class CityWeather(BaseModel):
    city: str
    temperature_f: float
    condition: str
    notes: str = ""


class WeatherAlert(BaseModel):
    city: str
    message: str


class WeatherEnvironment(TaskEnvironment):
    cities: dict[str, CityWeather]
    weather_alerts: list[WeatherAlert] = []
