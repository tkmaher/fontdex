import { ErrorResponse } from "@/types/error";
import { Match } from "effect";
import { ArrayFormatter } from "effect/ParseResult";
 
export const describeError = (error: ErrorResponse): string =>
  Match.value(error).pipe(
    Match.tag("NetworkError", () => "Couldn't reach the server."),
    Match.tag("HttpError", (_) => `Request failed (${_.e.status} ${_.e.statusText}).`),
    Match.tag("ParseError", (_) => ArrayFormatter.formatErrorSync(_.e)[0]?.message ?? "Invalid data."),
    Match.tag("TimeoutException", () => "The request timed out."),
    Match.orElse(() => "Something went wrong."),
);
 