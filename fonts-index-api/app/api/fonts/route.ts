/*
  Get a list of fonts based on heuristics.
*/
import { getCloudflareContext } from "@opennextjs/cloudflare";
import { Effect } from "effect";
import { SqlClient } from "@effect/sql";
import { makeDbLayer } from "@/lib/db";

// Define a schema or type for the query response
interface FontRow {
  font: string;
  classification: string;
  style_tags: string;
  source: string;
  subsets: string;
  notes: string;
  confidence: string;
}

// 1. Define your effectful SQL program
const getUsersProgram = (minId: number) =>
  Effect.gen(function* () {
    const sql = yield* SqlClient.SqlClient;

    // Use safe sql template tags to prevent SQL injection
    const rows = yield* sql<FontRow>`
      SELECT id, name, email 
      FROM users 
      WHERE id >= ${minId}
    `;

    return rows;
});

// 2. Handle the Next.js API Request
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const fontName = Number(searchParams.get("font") || "0");

  const context = getCloudflareContext();
  const env = context.env as CloudflareEnv;

  const dbLayer = makeDbLayer(env);
  const runnable = getUsersProgram(minId).pipe(Effect.provide(dbLayer));

  try {
    // Run the Effect pipeline and convert it into a promise
    const users = await Effect.runPromise(runnable);
    return Response.json({ success: true, data: users });
  } catch (error) {
    // Effectively catches database errors, timeout errors, or schema validation failures
    return Response.json(
      { success: false, error: "Database transaction failed" }, 
      { status: 500 }
    );
  }
}