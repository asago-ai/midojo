import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const REAL_WEATHER_DATA: Record<string, { temperature_f: number; condition: string }> = {
	"New York": { temperature_f: 72.0, condition: "sunny" },
	"San Francisco": { temperature_f: 58.0, condition: "foggy" },
	"Chicago": { temperature_f: 45.0, condition: "windy" },
};

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "get_weather",
		label: "Get Weather",
		description: "Get current weather for a city.",
		parameters: Type.Object({
			city: Type.String({ description: "The name of the city to get weather for" }),
		}),
		async execute(_toolCallId, params) {
			const city = (params as { city: string }).city;
			const data = REAL_WEATHER_DATA[city];
			if (!data) {
				return {
					content: [{ type: "text" as const, text: `No weather data available for ${city}` }],
					details: {},
				};
			}
			return {
				content: [{ type: "text" as const, text: `${city}: ${data.temperature_f}°F, ${data.condition}` }],
				details: {},
			};
		},
	});

	pi.registerTool({
		name: "list_cities",
		label: "List Cities",
		description: "List all cities with available weather data.",
		parameters: Type.Object({}),
		async execute() {
			return {
				content: [{ type: "text" as const, text: Object.keys(REAL_WEATHER_DATA).join(", ") }],
				details: {},
			};
		},
	});
}
