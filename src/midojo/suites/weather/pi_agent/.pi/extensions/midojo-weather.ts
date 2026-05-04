import { createMidojoExtension } from "../../../../../pi-sdk/src";
import { Type } from "typebox";

export default createMidojoExtension({
	controlPlaneUrl: process.env.MIDOJO_URL || "http://localhost:8080",
	runId: process.env.MIDOJO_RUN_ID!,
	evalId: process.env.MIDOJO_EVAL_ID!,
	tools: [
		{
			name: "get_weather",
			label: "Get Weather",
			description: "Get current weather for a city.",
			parameters: Type.Object({
				city: Type.String({ description: "The name of the city to get weather for" }),
			}),
			execute: async (params, ctx) => {
				/* The suite author can decide here whether to forward calls to
				the real tools and if/how to insert injected data from the
				environment.
				*/
				const cities = await ctx.env<Record<string, { temperature_f: number; condition: string; notes: string }>>(
					"cities",
				);
				const data = cities[params.city as string];
				if (!data) return `No weather data available for ${params.city}.`;
				let result = `Weather for ${params.city}: ${data.temperature_f}°F, ${data.condition}.`;
				if (data.notes) result += "\n" + data.notes;
				return result;
			},
		},
		{
			name: "list_cities",
			label: "List Cities",
			description: "List all cities with available weather data.",
			parameters: Type.Object({}),
			execute: async (_params, ctx) => {
				const cities = await ctx.env<Record<string, unknown>>("cities");
				return `Available cities: ${Object.keys(cities).join(", ")}`;
			},
		},
		{
			name: "send_weather_alert",
			label: "Send Weather Alert",
			description: "Send a weather alert for a city.",
			parameters: Type.Object({
				city: Type.String({ description: "The city the alert is for" }),
				message: Type.String({ description: "The alert message" }),
			}),
			execute: async (params, ctx) => {
				const alerts = await ctx.env<Array<{ city: string; message: string }>>("weather_alerts");
				alerts.push({ city: params.city as string, message: params.message as string });
				await ctx.envUpdate("weather_alerts", alerts);
				return `Weather alert sent for ${params.city}: ${params.message}`;
			},
		},
	],
});
