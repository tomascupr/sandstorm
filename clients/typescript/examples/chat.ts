/**
 * Minimal CLI example. Run against a local `ds serve`:
 *
 *   ds serve                           # in one terminal
 *   pnpm install
 *   pnpm tsx examples/chat.ts "your prompt here"
 */
import { SandstormClient } from "../src/index.js";

async function main() {
  const prompt = process.argv.slice(2).join(" ") || "Say hello";
  const client = new SandstormClient({
    baseUrl: process.env.SANDSTORM_URL ?? "http://localhost:8000",
    apiKey: process.env.SANDSTORM_API_KEY,
  });

  for await (const event of client.query({ prompt })) {
    if (!event.json || typeof event.json !== "object") continue;
    const msg = event.json as {
      type?: string;
      message?: { content?: Array<{ type: string; text?: string }> };
      subtype?: string;
      error?: string;
    };
    if (msg.type === "assistant") {
      for (const block of msg.message?.content ?? []) {
        if (block.type === "text" && block.text) {
          process.stdout.write(block.text);
        }
      }
    } else if (msg.type === "error") {
      process.stderr.write(`\nError: ${msg.error}\n`);
      process.exit(1);
    } else if (msg.type === "result") {
      process.stdout.write(`\n\n--- Result: ${msg.subtype} ---\n`);
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
