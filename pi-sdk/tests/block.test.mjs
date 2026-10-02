import assert from "node:assert/strict";
import { test } from "node:test";
import { BLOCKED_REASON, createMidojoExtension } from "../src/index.ts";

test("blocked tools are recorded as blocked and stopped", async () => {
	const originalFetch = globalThis.fetch;
	const previousToken = process.env.MIDOJO_SESSION_TOKEN;
	const handlers = {};
	const recorded = [];
	globalThis.fetch = async (_url, init) => {
		recorded.push(JSON.parse(init.body));
		return new Response("{}", { status: 201 });
	};
	try {
		process.env.MIDOJO_SESSION_TOKEN = "session";
		createMidojoExtension({ controlPlaneUrl: "http://control", blockTools: ["send_email"] })({
			on: (event, callback) => {
				handlers[event] = callback;
			},
		});
		const input = { to: "bookings@travel-sync.example" };
		assert.deepEqual(await handlers.tool_call({ toolName: "send_email", input }), {
			block: true,
			reason: BLOCKED_REASON,
		});
		assert.equal(await handlers.tool_call({ toolName: "get_weather", input: {} }), undefined);
		assert.deepEqual(recorded, [{ function: "send_email", args: input, result: BLOCKED_REASON, blocked: true }]);
	} finally {
		globalThis.fetch = originalFetch;
		if (previousToken === undefined) delete process.env.MIDOJO_SESSION_TOKEN;
		else process.env.MIDOJO_SESSION_TOKEN = previousToken;
	}
});
