"use client";
import '@/app/styles/form.scss';
import { useFontSearch } from "@/components/effects/fetch-fonts";

import { use, useMemo, useState } from "react";
import { Schema } from "effect";
import { ArrayFormatter } from "effect/ParseResult";
import { FontFilter, FontRow, SiteFilter } from "@/types/schema";
import { Dropdown, DropdownAggregate } from '@/components/filters/dropdown';
import Toggle from '@/components/filters/toggle';
import FontBlock from '@/components/display/fontblock';
import Pagination from '@/components/display/pagination';
import CytoscapeGraph from '@/components/graph/graph';
import DisplayNav, { TagType } from '@/components/display/sitefontinspector';
import { useSiteSearch } from '../effects/fetch-font-sites';

type SearchValType = "title+desc" | "only title" | "only description";
type SearchFieldType = "td" | "t" | "d";
type SortValType = "popularity, desc" | "popularity, asc" | "a → z" | "z → a";
type SortByType = "popHL" | "popLH" | "fontAZ" | "fontZA";
type BubbleSortType = "classification" | "style_tags" | "subsets";

const CLASSIFICATION_FILTER: FontFilter = { bubbleSort: "classification", page: 1 };
const SUBSETS_FILTER: FontFilter = { bubbleSort: "subsets", page: 1 };
const STYLES_FILTER: FontFilter = { bubbleSort: "style_tags", page: 1 };

const CATEGORY_FILTER: FontFilter = { bubbleSort: "categories", page: 1 };

const INIT_ROW_FILTER: FontFilter = { page: 1, sortBy: "popHL" };

export default function FontSearchForm() {
  // --- form fields ---
  const [ searchString, setSearchString ] = useState<string>("");
  const [ searchVal, setSearchVal ] = useState<SearchValType>("title+desc");
  const [ classification, setClassification ] = useState<string>("");
  const [ styles, setStyles ] = useState<string[]>([]);
  const [ subsets, setSubsets ] = useState<string[]>([]);
  const [ styleOr, setStyleOr ] = useState<boolean>(true);
  const [ subsetOr, setSubsetOr ] = useState<boolean>(true);
  const [ sortVal, setSortVal ] = useState<SortValType>("popularity, desc");
  const [ sortBy, setSortBy ] = useState<SortByType>("popHL");
  const [ bubbleSort, setBubbleSort ] = useState<BubbleSortType>("classification");

  const [ searchingFonts, setSearchingFonts ] = useState(true);

  const [ category, setCategory ] = useState<string>("");

  // --- paging / view ---
  const [ pageIn, setPageIn ] = useState<number>(1);
  const [ viewMode, setViewMode ] = useState<boolean>(false); // false = row, true = bubble

  const [ formError, setFormError ] = useState<string | null>(null);

  const [ rowParams, setRowParams ] = useState<FontFilter | null>(INIT_ROW_FILTER);
  const [ bubbleParams, setBubbleParams ] = useState<FontFilter | null>(null);

  const [ siteRowParams, setSiteRowParams ] = useState<SiteFilter | null>(INIT_ROW_FILTER);
  const [ siteBubbleParams, setSiteBubbleParams ] = useState<SiteFilter | null>(null);

  const [ fontSelected, setFontSelected ] = useState<FontRow | null>(null);

  const searchField: SearchFieldType = useMemo(
    () => (searchVal === "title+desc" ? "td" : searchVal === "only title" ? "t" : "d"),
    [searchVal]
  );

  // Shared fields between row & bubble filters.
  const buildBaseFilter = () => ({
    searchString,
    classification: classification || undefined,
    styles,
    subsets,
    styleOr,
    subsetOr,
    sortBy,
    searchField,
  });

  const reportDecodeError = (left: Parameters<typeof ArrayFormatter.formatErrorSync>[0]) => {
    setFormError(ArrayFormatter.formatErrorSync(left)[0]?.message ?? "Invalid input.");
  };

  const submitRow = (page: number) => {
    const result = Schema.decodeUnknownEither(FontFilter)({ ...buildBaseFilter(), page });
    if (result._tag === "Left") {
      reportDecodeError(result.left);
      return false;
    }
    setFormError(null);
    setRowParams(result.right);
    setPageIn(page);
    return true;
  };

  const submitBubble = () => {
    const result = Schema.decodeUnknownEither(FontFilter)({
      ...buildBaseFilter(),
      page: 1,
      bubbleSort,
    });
    if (result._tag === "Left") {
      reportDecodeError(result.left);
      return false;
    }
    setFormError(null);
    setBubbleParams(result.right);
    return true;
  };
  
  const submit = (paging?: 'next' | 'back') => {
    if (viewMode) {
      setRowParams(null);
      submitBubble();
      return;
    }
    const page = paging ? (paging === 'next' ? pageIn + 1 : pageIn - 1) : 1;
    setBubbleParams(null);
    submitRow(page);
  };

  const handleViewSwitch = () => {
    const switchingToBubble = !viewMode;
    if (switchingToBubble && bubbleParams === null) {
      submitBubble();
    } else if (!switchingToBubble && rowParams === null) {
      submitRow(pageIn);
    }
    setViewMode(switchingToBubble);
  };

  const {
    data: results,
    error,
    isError,
    isFetching,
    refetch,
  } = searchingFonts ? useFontSearch(rowParams) : useSiteSearch(siteRowParams);

  const { data: bubbleResults } = searchingFonts ? useFontSearch(bubbleParams) : useSiteSearch(siteBubbleParams);

  const { data: classResults } = useFontSearch(CLASSIFICATION_FILTER);
  const { data: subsetResults } = useFontSearch(SUBSETS_FILTER);
  const { data: styleResults } = useFontSearch(STYLES_FILTER);
  const { data: categoryResults } = useSiteSearch(CATEGORY_FILTER);

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
  const categories = useMemo(
    () => (categoryResults?._tag === "BubbleSiteResult" ? categoryResults.data.map(i => `${i.label}`) : []),
    [categoryResults]
  );

  const queryFull = `
    ${classification ? 'classification: ' + classification + ';' : ''}
    ${styles.length > 0 ? 'styles: ' + styles.join(styleOr ? ' or ' : ' and ') + ';' : ''}
    ${subsets.length > 0 ? 'subsets: ' + subsets.join(subsetOr ? ' or ' : ' and ') + ';' : ''}
    ${searchString.length > 0 ? 'contains ' + searchString + ' in ' + searchVal + ';' : ''}
    ${'ordered by ' + sortVal}
  `;

  const queryFullSites = `
    ${category ? 'category: ' + category + ';' : ''}
    ${searchString.length > 0 ? 'contains ' + searchString + ';'  : ''}
    ${'ordered by ' + sortVal}
  `;

  const handleSortSelect = (selected: SortValType) => {
    setSortVal(selected);
    switch (selected) {
      case "popularity, desc": setSortBy("popHL"); break;
      case "popularity, asc": setSortBy("popLH"); break;
      case "a → z": setSortBy("fontAZ"); break;
      case "z → a": setSortBy("fontZA"); break;
      default: setSortBy("popHL");
    }
  };

  const clearFilters = () => {
    setSearchString("");
    setSearchVal("title+desc");
    setClassification("");
    setStyles([]);
    setSubsets([]);
    setStyleOr(true);
    setSubsetOr(true);
    setSortVal("popularity, desc");
    setSortBy("popHL");
    setCategory("");
  }

  const tagCallback = (data: TagType) => {
    clearFilters();
    setClassification(data.type === "classification" ? data.label : "");
    setStyles(data.type === "style" ? [data.label] : []);
    setSubsets(data.type === "subset" ? [data.label] : []);

    const result = Schema.decodeUnknownEither(FontFilter)({
      searchString: "",
      classification: data.type === "classification" ? data.label : undefined,
      styles: data.type === "style" ? [data.label] : [],
      subsets: data.type === "subset" ? [data.label] : [],
      styleOr: true,
      subsetOr: true,
      sortBy: "popHL",
      searchField,
      page: 1,
    });

    if (result._tag === "Left") {
      reportDecodeError(result.left);
      return;
    }
    setFormError(null);
    setBubbleParams(null);
    setViewMode(false);
    setPageIn(1);
    setRowParams(result.right);
  };

  return (
    <>
      <div className='right-stack'>
        <div className='search-row'>
          <button 
            type="button" 
            className='text submit' 
            onClick={() => setSearchingFonts(!searchingFonts)}
          >
            {searchingFonts ? "(browse fonts)" : "(browse sites)"}
          </button>
        </div>
        <form onSubmit={(event: React.FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          submit();
        }}>

          {searchingFonts ? 
            <>
              <div className='search-col'>
                <div className='text'>classification</div>
                <div className='search-row'>
                  <Dropdown
                    title=""
                    value={classification}
                    options={classifications}
                    setterCallback={setClassification}
                  />
                </div>
              </div>
              <div className='search-col'>
                <div className='text'>styles</div>
                <DropdownAggregate title='' options={stylesList} value={styles} setterCallback={setStyles} />
                {styles.length > 1 && <Toggle
                  value={styleOr}
                  setterCallback={setStyleOr}
                  str1="inclusive"
                  str2="exclusive"
                />}
              </div>
              <div className='search-col'>
                <div className='text'>subsets</div>
                <DropdownAggregate title='' options={subsetsList} value={subsets} setterCallback={setSubsets} />
                {subsets.length > 1 && <Toggle
                  value={subsetOr}
                  setterCallback={setSubsetOr}
                  str1="inclusive"
                  str2="exclusive"
                />}
              </div>
            </> : 
            <div className='search-col'>
              <div className='text'>category</div>
              <div className='search-row'>
                <Dropdown
                  title=""
                  value={category}
                  options={categories}
                  setterCallback={setCategory}
                />
              </div>
            </div>
          }
          <div className='search-col'>
            <div className='text'>filter</div>
            <div className='search-row'>
              <input
                type="text"
                id="searchstring"
                value={searchString}
                placeholder='contains…'
                onChange={(e) => setSearchString(e.target.value)}
              />
              {searchingFonts && <Dropdown
                title="title+desc"
                value={searchVal}
                options={["title+desc", "only title", "only description"]}
                setterCallback={setSearchVal}
                removeNegate
                removeRemove
              />}
              {searchString.length > 0 &&
                <button
                    type="button"
                    className="text button-not img-btn"
                    onClick={() => setSearchString('')}
                >
                    ×
                </button>
              }
            </div>
          </div>
          <div className='search-col'>
            <div className='text'>order</div>
            <Dropdown
              title={sortVal}
              value={sortVal}
              options={["popularity, desc", "popularity, asc", "a → z", "z → a"]}
              setterCallback={handleSortSelect}
              removeNegate
              removeRemove
            />
          </div>

          {formError && <p>{formError}</p>}
        </form>

        <div className='search-col'>
          <div className='search-row text' style={{width: 'auto'}}>
            {searchingFonts ? queryFull : queryFullSites}
          </div>
          <div className='search-row'>
            <button type="submit" className='text submit' disabled={isFetching} onClick={() => submit()}>
              search
            </button>
            <button type="button" className='text' disabled={isFetching} onClick={clearFilters}>
              clear
            </button>

          </div>
          {isError && (
            <div>
              <button className='text' style={{pointerEvents: 'none'}}>{error instanceof Error ? error.message : "Something went wrong."}</button>
              <button onClick={() => refetch()}>Retry</button>
            </div>
          )}
        </div>
      </div>
      <div className='left-container'>

        <div className='left-split'>
          <div className={`left-stack ${fontSelected ? 'left-split-small' : 'left-split-large'}`}>
          <div className='search-row' style={{justifyContent: 'center'}}>
            <button 
              type='button' 
              className='text' 
              onClick={handleViewSwitch}
              style={{
                flexGrow: 1,
                marginRight: fontSelected ? '1px' : '0px',
              }}
            >
              (switch view)
            </button>

          </div>
            {!viewMode
              ? results?._tag === "RowFontResult" && (
                  <div className='boxes'>
                    {results.data.map((row, i) => (
                      <FontBlock 
                        row={row} 
                        index={i} 
                        setter={async () => setFontSelected(row)} 
                        selected={fontSelected?.font === row.font}
                        key={i} 
                      />
                    ))}
                  </div>
                )
              : bubbleResults?._tag === "BubbleFontResult" && (
                  <CytoscapeGraph fontdata={bubbleResults} />
                )
            }
            {!viewMode && <Pagination submit={submit} results={results} pageIn={pageIn} disabled={isFetching}/>}
          </div>
          {fontSelected && 
            <DisplayNav 
              current={fontSelected} 
              tagCallback={tagCallback}
              closeInspector={() => setFontSelected(null)}
            />
          }
        </div>


      </div>
    </>
  );
}