import { Data } from "effect";
import { ParseError } from "effect/ParseResult";

export class NetworkError extends Data.TaggedError("NetworkError")<{
    cause: unknown;
  }> {}

export class HttpError extends Data.TaggedError("HttpError")<{
    status: number;
    statusText: string;
}> {}

export type ErrorResponse = 
  | { _tag: "NetworkError"; }
  | { _tag: "TimeoutException"; }
  | { _tag: "HttpError"; e: HttpError }
  | { _tag: "ParseError"; e: ParseError };

