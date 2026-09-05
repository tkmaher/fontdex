import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { Duration, Effect, Schedule, Schema } from "effect";
import { SiteResult, type SiteFilter } from "@/types/schema";
import { describeError } from "./error";
import { NetworkError, HttpError } from "@/types/error";

const SITES_API_URL = "https://fonts-index-api.tomaszkkmaher.workers.dev/api/sites";

const fetchSitesEffect = (filter: SiteFilter) => Effect.gen(function* () {
  const url = new URL(SITES_API_URL);
  filter.font && url.searchParams.set("font", filter.font);
  url.searchParams.set("page", String(filter.page));
  url.searchParams.set("sortBy", String(filter.sortBy));
  filter.category && url.searchParams.set("category", filter.category);
  filter.searchString && url.searchParams.set("searchString", filter.searchString);
  filter.bubbleSort && url.searchParams.set("bubbleSort", String(filter.bubbleSort));

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

  const tagged = filter.bubbleSort
  ? {
      ...rawResult,
      _tag: "BubbleSiteResult",
    }
  : {
      ...rawResult,
      data: Array.isArray(rawResult.data)
        ? (rawResult.data as Record<string, unknown>[]).map((row) => ({
            ...row,
            _tag: "SiteRow",
          }))
        : rawResult.data,
      _tag: "RowSiteResult",
    };

  return yield* Schema.decodeUnknown(SiteResult)(tagged).pipe(
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

export const runFetchSites = (params: SiteFilter) => Effect.runPromise(
  fetchSitesEffect(params).pipe(Effect.mapError(
    (error: unknown) => new Error(describeError(error))
  )),
);

export const useSiteSearch = (params: SiteFilter | null) => useQuery({
  queryKey: ["sites", params] as const,
  queryFn: ({ queryKey: [, p] }) => runFetchSites(p!),
  enabled: params !== null,
  staleTime: Duration.toMillis(Duration.minutes(1)),
  placeholderData: (previousData, previousQuery) => {
    const previousParams = previousQuery?.queryKey?.[1] as SiteFilter | null | undefined;
    if (!previousParams || !params) return undefined;
    const { page: _prevPage, ...prevRest } = previousParams;
    const { page: _curPage, ...curRest } = params;
    return JSON.stringify(prevRest) === JSON.stringify(curRest)
      ? previousData
      : undefined;
  },
  retry: false,
});