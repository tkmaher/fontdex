"use client";
import { FontRow, SiteFilter, SiteRow } from "@/types/schema";
import { useSiteSearch } from "../effects/fetch-font-sites";
import { useEffect, useRef, useState } from "react";
import Pagination from "@/components/display/pagination";
import { useFontLookup } from "../effects/fetch-font";
import { BubbleSortType } from "../filters/fontsearch-form";

function SiteInspector({
    site,
    catCallback,
    navCallback
}: {
    site: SiteRow,
    catCallback: (category: string, clearBefore: boolean) => void,
    navCallback: (item: FontRow | SiteRow) => void
}) {
    const fontSlots = [site.font1, site.font2, site.font3];
    const results = fontSlots.map(font => useFontLookup(font ?? ""));
    const activeResults = results.filter((_, i) => Boolean(fontSlots[i]));
    const allFetched = activeResults.every(r => !r.isFetching);
    const loadedFonts = activeResults
        .map(r => r.data)
        .filter((font): font is FontRow => Boolean(font));

    return (
        <>
            <div className="font-inspector">
                <div className="inspector-title">
                    <div className="text">{site.domain}</div>
                    <button
                        type="button"
                        className="img-btn text"
                        onClick={() => window.open(`https://${site.domain}`, '_blank')}
                    >
                        <img src="link.svg" />
                    </button>
                </div>
                <div className="inspector-desc text">Ranked #{site.rank}</div>
                <div className="tag-map">
                    <button
                        className='button-img-rev'
                        onClick={() => catCallback(site.category, true)}
                    >
                        {site.category}
                    </button>
                </div>
                <div className="inspector-sub text">Fonts</div>
            </div>
            <div className="inspector-sites">
                {!allFetched ? (
                    <div className="text">loading…</div>
                ) : (
                    loadedFonts.map((font, i) => (
                        <div className="search-row" key={font.font ?? i}>
                            <button className="text" onClick={() => navCallback(font)}>
                                {font.font}
                            </button>
                        </div>
                    ))
                )}
            </div>
        </>
    );
}

export interface TagType {
    label: string,
    type: BubbleSortType
}

function buildTags(row: FontRow): TagType[] {
    const styleTags: TagType[] = row.style_tags
        ? row.style_tags.split(';').map(label => ({ label, type: "style_tags" as const }))
        : [];
    const subsetTags: TagType[] = row.subsets
        ? row.subsets.split(';').map(label => ({ label, type: "subsets" as const }))
        : [];
    return [
        { label: row.classification, type: "classification" as const },
        ...styleTags,
        ...subsetTags,
    ].sort((a, b) => a.label.localeCompare(b.label));
}

function FontInspector({
    row,
    tagCallback,
    navCallback,
}: {
    row: FontRow,
    tagCallback: (data: TagType, clearBefore: boolean) => void,
    navCallback: (item: FontRow | SiteRow) => void,
}) {

    const [ page, setPage ] = useState<number>(1);
    const [ siteParams, setSiteParams ] = useState<SiteFilter | null>({ font: row.font, page: 1, sortBy: "popHL" });

    useEffect(() => {
        setPage(1);
        setSiteParams({ font: row.font, page: 1, sortBy: "popHL" });
    }, [row.font]);

    const submit = (paging?: 'next' | 'back') => {
        const nextPage = paging ? (paging === 'next' ? page + 1 : page - 1) : 1;
        setSiteParams({ font: row.font, page: nextPage, sortBy: "popHL" });
        setPage(nextPage);
    };

    const {
        data: results,
        error,
        isError,
        isFetching,
        refetch,
    } = useSiteSearch(siteParams);

    const tags = buildTags(row);

    const containerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (containerRef.current) {
            containerRef.current.scrollTop = 0;
        }
    }, [row, isFetching]);

    return (
        <>
            <div className="font-inspector">
                <div className="inspector-title text">{row.font}</div>
                <div className="inspector-desc text">{row.notes}</div>
                <div className="tag-map">
                    {tags.map((tag, i) => (
                        <div key={i}>
                            <button
                                className={
                                    tag.type === 'style_tags' ? 'button-rev'
                                        : tag.type === 'classification' ? 'button-not-rev'
                                        : 'button-img-rev'
                                }
                                onClick={() => tagCallback(tag, true)}
                            >
                                {tag.label}
                            </button>
                        </div>
                    ))}
                </div>
                <div className="inspector-sub text">{row.hits} site{row.hits != 1 && 's'}</div>
            </div>
            <div className="inspector-sites" ref={containerRef}>
                {isFetching ? (
                    <div className="text">loading…</div>
                ) : 
                    results?._tag == "RowSiteResult" && results.data.map((site, i) => (
                        <div className="search-row" key={site.domain ?? i}>
                            <button
                                className="text"
                                onClick={() => navCallback(site)}
                            >
                                {site.domain}
                            </button>
                            <button
                                type="button"
                                style={{ width: '16px' }}
                                className='img-btn button-not text'
                                onClick={() => window.open(`https://${site.domain}`, '_blank')}
                            >
                                <img src='link.svg' />
                            </button>
                        </div>
                    ))
                }
                {isError &&
                    <div>
                        <button type="button" className='text' style={{ pointerEvents: 'none' }}>
                            {error instanceof Error ? error.message : "Something went wrong."}
                        </button>
                        <button type="button" onClick={() => refetch()}>Retry</button>
                    </div>
                }
            </div>

            <Pagination submit={submit} results={results} pageIn={page} disabled={isFetching} />
        </>
    );
}

export default function DisplayNav({
    current,
    tagCallback,
    catCallback,
    closeInspector
}: {
    current: SiteRow | FontRow,
    tagCallback: (data: TagType, clearBefore: boolean) => void,
    catCallback: (category: string, clearBefore: boolean) => void
    closeInspector: () => void
}) {

    const [selected, setSelected] = useState<(SiteRow | FontRow)>(current);
    const [index, setIndex] = useState(0);
    const [history, setHistory] = useState<(SiteRow | FontRow)[]>([current]);

    useEffect(() => {
        setHistory([current]);
        setIndex(0);
        setSelected(current);
    }, [current]);

    const navigateTo = (item: SiteRow | FontRow) => {
        const nextHistory = [...history.slice(0, index + 1), item];
        setHistory(nextHistory);
        setIndex(nextHistory.length - 1);
        setSelected(item);
    };

    const goBack = () => {
        setSelected(history[index - 1]);
        setIndex(index - 1);
    };

    const goForward = () => {
        setSelected(history[index + 1]);
        setIndex(index + 1);
    };

    const canGoBack = index > 0;
    const canGoForward = index < history.length - 1;

    return (
        <div className="display-screen">
            <div className="search-row">
                <button
                    type="button"
                    className="text img-btn"
                    style={{
                        pointerEvents: canGoBack ? 'all' : 'none',
                        opacity: canGoBack ? '1' : '0.5'
                    }}
                    onClick={goBack}
                >
                    <img src="back.svg" />
                </button>
                <button
                    type="button"
                    className="text img-btn"
                    style={{
                        pointerEvents: canGoForward ? 'all' : 'none',
                        opacity: canGoForward ? '1' : '0.5'
                    }}
                    onClick={goForward}
                >
                    <img src="forward.svg" />
                </button>
                <div className="text" style={{ flexGrow: 1 }}>
                    {selected._tag == "FontRow" ? 'Font' : 'Site'}
                </div>
                <button
                    type="button"
                    className="text button-not img-btn"
                    onClick={closeInspector}
                >
                    ×
                </button>
            </div>
            {selected._tag == "FontRow" ? (
                <FontInspector
                    row={selected}
                    tagCallback={tagCallback}
                    navCallback={navigateTo}
                />
            ) : (
                <SiteInspector
                    site={selected}
                    catCallback={catCallback}
                    navCallback={navigateTo}
                />
            )}
        </div>
    );
}