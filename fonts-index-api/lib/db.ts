import { D1Client } from "@effect/sql-d1";
import { SqlClient } from "@effect/sql";
import { Layer } from "effect";

// Factory function to build the SQL client layer dynamically using the request's cloudflare env
export const makeDbLayer = (env: CloudflareEnv) => {
  return D1Client.layer({
    db: env.DB
  });
};