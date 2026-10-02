// The import path is relative to this file's location inside the image
// (/sandbox/.pi/agent/extensions/ -> /sandbox/.pi/agent/pi-sdk/src), not the
// repo layout (see Containerfile).
import { createMidojoExtension } from "../pi-sdk/src";

export default createMidojoExtension({
	controlPlaneUrl: process.env.MIDOJO_URL || "http://localhost:8080",

	hooks: [
		{
			toolName: "get_weather",
			execute: async (args, realResult, ctx) => {
				const cities = await ctx.env<Record<string, { notes?: string }>>("cities");
				const data = cities[args.city as string];
				if (data?.notes) {
					return realResult + "\n" + data.notes;
				}
				return realResult;
			},
		},
	],

	// Record PI's built-in file tools without changing their results, so an
	// injection in a workspace file counts as reaching the agent.
	reportTools: ["read", "bash"],

	// Never send email during an evaluation. The control plane still records
	// the agent's attempt, marked as blocked.
	blockTools: ["send_email"],
});
