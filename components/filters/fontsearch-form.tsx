"use client";
import '@/app/styles/form.scss';
import { useFontSearch } from "@/components/effects/fetch-fonts";

import { useEffect, useMemo, useState } from "react";
import { Schema } from "effect";
import { ArrayFormatter } from "effect/ParseResult";
import { BubbleFontResult, FontFilter } from "@/types/schema";
import { Dropdown, DropdownAggregate } from './dropdown';
import Toggle from './toggle';

type FontSearchFormProps = {
  onBubbleResult?: (result: BubbleFontResult) => void;
};

type SearchValType = "title+desc" | "only title" | "only description";
type SearchFieldType = "td" | "t" | "d";
type SortValType = "popularity, desc" | "popularity, asc" | "a → z" | "z → a";
type SortByType = "popHL" | "popLH" | "fontAZ" | "fontZA"

const CLASSIFICATION_FILTER: FontFilter = { bubbleSort: "classification", page: 1 };
const SUBSETS_FILTER: FontFilter = { bubbleSort: "subsets", page: 1 };
const STYLES_FILTER: FontFilter = { bubbleSort: "style_tags", page: 1 };

export default function FontSearchForm({ onBubbleResult }: FontSearchFormProps) {
  const [ searchString, setSearchString ] = useState<string>("");
  const [searchVal, setSearchVal] = useState<SearchValType>("title+desc");
  const [ classification, setClassification ] = useState<string>("");
  const [ styles, setStyles ] = useState<string[]>([]);
  const [ subsets, setSubsets ] = useState<string[]>([]);
  const [ styleOr, setStyleOr ] = useState<boolean>(false);
  const [ subsetOr, setSubsetOr ] = useState<boolean>(false);
  const [ sortVal, setSortVal ] = useState<SortValType>("popularity, desc");
  const [ sortBy, setSortBy ] = useState<SortByType>("popHL");
  const [ page, setPage ] = useState<number>(1);
  const [ bubbleSort, setBubbleSort ] = useState<"classification" | "style_tags" | "subsets" | undefined>(undefined); 

  const [formError, setFormError] = useState<string | null>(null);
  const [params, setParams] = useState<FontFilter | null>(null);

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
  
    const searchField: SearchFieldType =
      searchVal === "title+desc"
        ? "td"
        : searchVal === "only title"
          ? "t"
          : "d";
  
    const result = Schema.decodeUnknownEither(FontFilter)({
      searchString,
      classification: classification || undefined,
      styles,
      subsets,
      styleOr,
      subsetOr,
      sortBy,
      page,
      bubbleSort,
      searchField,
    });
  
    console.log("sending:", result);
  
    if (result._tag === "Left") {
      setFormError(
        ArrayFormatter.formatErrorSync(result.left)[0]?.message ??
          "Invalid input."
      );
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


  const { data: classResults } = useFontSearch(CLASSIFICATION_FILTER);
  const { data: subsetResults } = useFontSearch(SUBSETS_FILTER);
  const { data: styleResults } = useFontSearch(STYLES_FILTER);

  const classifications = useMemo(
    () => (classResults?._tag === "BubbleFontResult" ? classResults.data.map(i => `${i.label}`) : []),
    [classResults]
  );
  const stylesList = useMemo(
    () => (styleResults?._tag === "BubbleFontResult" ? styleResults.data.map(i => `${i.label}`) : []),
    [styleResults]
  );
  const subsetsList = useMemo(
    () => (subsetResults?._tag === "BubbleFontResult" ? subsetResults.data.map(i => `${i.label}`) : []),
    [subsetResults]
  );

  useEffect(() => {
    if (results?._tag === "BubbleFontResult") {
      onBubbleResult?.(results);
    }
  }, [results, onBubbleResult]);


  const handleSortSelect = (selected: SortValType) => {
    setSortVal(selected);
    switch (selected) {
      case "popularity, desc":
        setSortBy("popHL");
        break;
      case "popularity, asc":
        setSortBy("popLH");
        break;
      case "a → z":
        setSortBy("fontAZ");
        break;
      case "z → a":
        setSortBy("fontZA");
        break;
      default:
        setSortBy("popHL");
    }
  }

  return (
    <div className='right-stack'>
      <form onSubmit={submit}>
        <div className='search-row'>
          <Dropdown 
            title="classification" 
            value={classification}
            options={classifications} 
            setterCallback={setClassification} 
          />
        </div>
        <DropdownAggregate title='style' options={stylesList} setterCallback={setStyles} />
        {styles.length > 1 && <Toggle 
          value={styleOr} 
          setterCallback={setStyleOr} 
          str1="Inclusive"
          str2="Exclusive"
        />}
        <DropdownAggregate title='subset' options={subsetsList} setterCallback={setSubsets} />
        {subsets.length > 1 && <Toggle 
          value={subsetOr} 
          setterCallback={setSubsetOr} 
          str1="Inclusive"
          str2="Exclusive"
        />}
        <div className='search-row'>
          <input 
            type="text" 
            id="searchstring" 
            value={searchString} 
            placeholder='Contains…'
            onChange={(e) => setSearchString(e.target.value)} 
          />
          <Dropdown 
            title="title+desc" 
            value={searchVal}
            options={["title+desc", "only title", "only description"]} 
            setterCallback={setSearchVal} 
            removeNegate
            removeRemove
          />
        </div>
        <Dropdown 
          title={sortVal}
          value={sortVal}
          options={["popularity, desc", "popularity, asc", "a → z", "z → a"]}
          setterCallback={handleSortSelect} 
          removeNegate
          removeRemove
        />
        
        {formError && <p>{formError}</p>}

        <button type="submit" className='text' disabled={isFetching}>
          {isFetching ? "Searching…" : "Search"}
        </button>
      </form>

      {isError && (
        <div>
          <p>{error instanceof Error ? error.message : "Something went wrong."}</p>
          <button onClick={() => refetch()}>Retry</button>
        </div>
      )}
    {styles} // TODO: robust query visualization
    </div>
  );
}