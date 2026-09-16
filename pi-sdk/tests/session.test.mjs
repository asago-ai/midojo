import assert from "node:assert/strict";
import { test } from "node:test";
import { ControlPlaneClient, createMidojoExtension, withMidojoSession } from "../src/index.ts";

test("one SDK client keeps concurrent task tokens separate on every callback", async () => {
	const requests = [];
	const originalFetch = globalThis.fetch;
	globalThis.fetch = async (url, init) => {
		await new Promise(resolve => setImmediate(resolve));
		requests.push({ token: init.headers.Authorization, path: new URL(url).pathname, method: init.method, body: init.body });
		return new Response(init.method === "GET" ? '{"count": 1}' : '{}', { status: 200 });
	};
	try {
		const client = new ControlPlaneClient("http://control");
		await Promise.all(["a", "b"].map(token => withMidojoSession(token, async () => {
			assert.deepEqual(await client.getEnvironment(), { count: 1 });
			await client.putEnvironment({ count: 2 });
			await client.recordFunctionCall({ function: "read", args: {}, result: token });
			await client.recordObservations("test", { token });
		})));
		for (const token of ["a", "b"]) {
			const own = requests.filter(req => req.token === `Bearer ${token}`);
			assert.equal(own.length, 4);
			assert.deepEqual(own.map(req => req.path), [
				"/agent/environment", "/agent/environment", "/agent/function-calls", "/agent/observations",
			]);
			assert.equal(JSON.parse(own[2].body).result, token);
		}
		const previous = process.env.MIDOJO_SESSION_TOKEN;
		delete process.env.MIDOJO_SESSION_TOKEN;
		try {
			await assert.rejects(() => client.getEnvironment(), /No MiDojo evaluation session/);
		} finally {
			if (previous !== undefined) process.env.MIDOJO_SESSION_TOKEN = previous;
		}
	} finally {
		globalThis.fetch = originalFetch;
	}
});

test("expired session errors from passive reporters are visible", async () => {
	const originalFetch = globalThis.fetch;
	const handlers = [];
	globalThis.fetch = async () => new Response('{}', { status: 401 });
	try {
		createMidojoExtension({ controlPlaneUrl: "http://control", reportTools: ["read"] })({
			on: (event, callback) => handlers.push(callback),
		});
		await assert.rejects(() => withMidojoSession("expired", () => handlers[0]({
			toolName: "read", input: {}, content: [{ type: "text", text: "report" }],
		})), /401/);
	} finally {
		globalThis.fetch = originalFetch;
	}
});
