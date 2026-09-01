import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { Duration, Effect, Schedule, Schema } from "effect";
import { FontRow } from "@/types/schema";
import { describeError } from "./error";
import { NetworkError, HttpError } from "@/types/error";

const FONT_API_URL = "https://fonts-index-api.tomaszkkmaher.workers.dev/api/font";
 
const fetchFontsEffect = (filter: string) => Effect.gen(function* () {
  const url = new URL(FONT_API_URL);
  url.searchParams.set("font", String(filter));

  const response = yield* Effect.tryPromise({
    try: (signal) => fetch(url, { signal }),
    catch: (cause) => new NetworkError({ cause }),
  });

  if (!response.ok) {
    return yield* new HttpError({
      status: response.status,
      statusText: response.statusText,
    });
  }


  const json = yield* Effect.tryPromise({
    try: () => response.json() as Promise<unknown>,
    catch: (cause) => new NetworkError({ cause }),
  });

  const rawResult = json as Record<string, unknown>;

  const font = rawResult.font as Record<string, unknown> | undefined;
  const tagged = {
    ...font,
    _tag: "FontRow"
  };


  return yield* Schema.decodeUnknown(FontRow)(tagged).pipe(
    Effect.mapError((cause) => new Error(`Failed to decode response: ${String(cause)}`)),
  );

}).pipe(
  Effect.timeout(Duration.seconds(8)),
  Effect.retry({
    schedule: Schedule.exponential(Duration.millis(200), 2).pipe(
      Schedule.compose(Schedule.recurs(3)),
    ),
    while: (error: unknown) => error instanceof NetworkError || error instanceof HttpError,
  }),
);
 
export const runFetchUsers = (params: string) => Effect.runPromise(
  fetchFontsEffect(params).pipe(Effect.mapError(
    (error: unknown) => new Error(describeError(error))
  )),
);

export const useFontLookup = (params: string) => useQuery({
  queryKey: ["results", params] as const,
  queryFn: ({ queryKey: [, p] }) => runFetchUsers(p!),
  enabled: !!params,
  staleTime: Duration.toMillis(Duration.minutes(1)),
  placeholderData: keepPreviousData,
  retry: false,
});