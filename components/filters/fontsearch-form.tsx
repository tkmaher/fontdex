"use client";

import { useFontSearch } from "@/components/effects/fetch-fonts";

import { useEffect, useState } from "react";
import { Schema } from "effect";
import { ArrayFormatter } from "effect/ParseResult";
import { BubbleFontResult, FontFilter } from "@/types/schema";

type FontSearchFormProps = {
  onBubbleResult?: (result: BubbleFontResult) => void;
};

export default function FontSearchForm({ onBubbleResult }: FontSearchFormProps) {
  const [ searchString, setSearchString ] = useState<string>("");
  const [ classification, setClassification ] = useState<string>("");
  const [ styles, setStyles ] = useState<string[]>([]);
  const [ subsets, setSubsets ] = useState<string[]>([]);
  const [ styleOr, setStyleOr ] = useState<boolean>(false);
  const [ subsetOr, setSubsetOr ] = useState<boolean>(false);
  const [ sortBy, setSortBy ] = useState<"popHL" | "popLH" | "fontAZ" | "fontZA">("popHL");
  const [ page, setPage ] = useState<number>(1);
  const [ bubbleSort, setBubbleSort ] = useState<"classification" | "style_tags" | "subsets" | null>("classification"); // TODO: change back

  const [formError, setFormError] = useState<string | null>(null);
  const [params, setParams] = useState<FontFilter | null>(null);

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const result = Schema.decodeUnknownEither(FontFilter)({
      searchString,
      classification: classification || undefined,
      styles,
      subsets,
      styleOr,
      subsetOr,
      sortBy,
      page,
      bubbleSort
    });

    if (result._tag === "Left") {
      setFormError(ArrayFormatter.formatErrorSync(result.left)[0]?.message ?? "Invalid input.");
      return;
    }

    setFormError(null);
    setParams(result.right);
  };

  const { 
    data: results, 
    error, 
    isError, 
    isFetching, 
    refetch 
  } = useFontSearch(params); 

  useEffect(() => {
    if (results?._tag === "BubbleFontResult") {
      onBubbleResult?.(results);
    }
  }, [results, onBubbleResult]);

  console.log("Results:", results);
  return (
    <div>
      <form onSubmit={submit}>
        <div>
          <label htmlFor="searchstring">Search query</label>
          <input id="searchstring" value={searchString} onChange={(e) => setSearchString(e.target.value)} />
        </div>
        
        {formError && <p>{formError}</p>}

        <button type="submit" disabled={isFetching}>
          {isFetching ? "Searching…" : "Search"}
        </button>
      </form>

      {isError && (
        <div>
          <p>{error instanceof Error ? error.message : "Something went wrong."}</p>
          <button onClick={() => refetch()}>Retry</button>
        </div>
      )}

    </div>
  );
}