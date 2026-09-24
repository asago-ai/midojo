import assert from "node:assert/strict";
import { test } from "node:test";
import { createMidojoExtension } from "../src/index.ts";

test("passive reporters surface missing and rejected sessions", async () => {
	const originalFetch = globalThis.fetch;
	const previousToken = process.env.MIDOJO_SESSION_TOKEN;
	const handlers = [];
	let requests = 0;
	globalThis.fetch = async () => {
		requests++;
		return new Response('{}', { status: 401 });
	};
	try {
		delete process.env.MIDOJO_SESSION_TOKEN;
		createMidojoExtension({ controlPlaneUrl: "http://control", reportTools: ["read"] })({
			on: (event, callback) => handlers.push(callback),
		});
		const report = () => handlers[0]({
			toolName: "read", input: {}, content: [{ type: "text", text: "report" }],
		});
		await assert.rejects(report, /No MiDojo evaluation session/);
		assert.equal(requests, 0);
		process.env.MIDOJO_SESSION_TOKEN = "expired";
		await assert.rejects(report, /401/);
		assert.equal(requests, 1);
	} finally {
		globalThis.fetch = originalFetch;
		if (previousToken === undefined) delete process.env.MIDOJO_SESSION_TOKEN;
		else process.env.MIDOJO_SESSION_TOKEN = previousToken;
	}
});
