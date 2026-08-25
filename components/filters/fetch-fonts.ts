import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { Duration, Effect, Schedule, Schema } from "effect";
import { FontResult, type FontFilter } from "@/types/schema";
import { describeError } from "./error";
import { NetworkError, HttpError } from "@/types/error";

const FONT_API_URL = "https://fonts-index-api.tomaszkkmaher.workers.dev/api/fonts";
 
const fetchFontsEffect = (filter: FontFilter) => Effect.gen(function* () {

  const url = new URL(FONT_API_URL);
  filter.searchString && url.searchParams.set("searchString", filter.searchString);
  filter.classification && url.searchParams.set("classification", filter.classification);
  filter.styles.forEach((style: string) =>
    url.searchParams.append("style", style)
  );
  filter.subsets.forEach((subset: string) =>
    url.searchParams.append("subset", subset)
  );
  url.searchParams.set("styleOr", String(filter.styleOr).toLowerCase());
  url.searchParams.set("subsetOr", String(filter.subsetOr).toLowerCase());
  url.searchParams.set("sortBy", String(filter.sortBy));
  url.searchParams.set("page", String(filter.page));

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

  console.log("Fetched JSON:", json);

  return yield* Effect.try({
    try: () => Schema.decodeUnknownEither(FontResult)(json),
    catch: (cause) => new Error(`Failed to decode response: ${cause}`),
  });
}).pipe(
  Effect.timeout(Duration.seconds(8)),
  Effect.retry({
    schedule: Schedule.exponential(Duration.millis(200), 2).pipe(
      Schedule.compose(Schedule.recurs(3)),
    ),
    while: (error: unknown) => error instanceof NetworkError || error instanceof HttpError,
  }),
);
 
export const runFetchUsers = (params: FontFilter) => Effect.runPromise(
  fetchFontsEffect(params).pipe(Effect.mapError(
    (error: unknown) => new Error(describeError(error))
  )),
);

export const useFontSearch = (params: FontFilter | null) => useQuery({
  queryKey: ["results", params] as const,
  queryFn: ({ queryKey: [, p] }) => runFetchUsers(p!),
  enabled: params !== null,
  staleTime: Duration.toMillis(Duration.minutes(1)),
  placeholderData: keepPreviousData,
  retry: false,
});