import assert from "node:assert/strict";
import { test } from "node:test";
import { ControlPlaneClient, createMidojoExtension, withMidojoSession } from "../src/index.ts";

test("one SDK client keeps concurrent task tokens separate on every callback", async () => {
	const requests = [];
	const originalFetch = globalThis.fetch;
	const previousToken = process.env.MIDOJO_SESSION_TOKEN;
	globalThis.fetch = async (url, init) => {
		await new Promise(resolve => setImmediate(resolve));
		requests.push({ token: init.headers.Authorization, path: new URL(url).pathname, method: init.method, body: init.body });
		return new Response(init.method === "GET" ? '{"count": 1}' : '{}', { status: 200 });
	};
	try {
		delete process.env.MIDOJO_SESSION_TOKEN;
		const client = new ControlPlaneClient("http://control///");
		process.env.MIDOJO_SESSION_TOKEN = "sandbox";
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
		await client.getEnvironment();
		assert.equal(requests.at(-1).token, "Bearer sandbox");
		delete process.env.MIDOJO_SESSION_TOKEN;
		const requestCount = requests.length;
		await assert.rejects(() => client.getEnvironment(), /No MiDojo evaluation session/);
		assert.equal(requests.length, requestCount);
	} finally {
		globalThis.fetch = originalFetch;
		if (previousToken === undefined) delete process.env.MIDOJO_SESSION_TOKEN;
		else process.env.MIDOJO_SESSION_TOKEN = previousToken;
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
