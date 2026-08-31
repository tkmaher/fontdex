"use client";
import { FontRow, SiteFilter, SiteRow } from "@/types/schema";
import { useSiteSearch } from "../effects/fetch-font-sites";
import { useEffect, useState } from "react";
import Pagination from "@/components/display/pagination";

function SiteInspector({
    site, 
    catCallback
}: {
    site: SiteRow, 
    catCallback: (category: string) => void
}) {

    const fonts = [site.font1, site.font2, site.font3]

    return (
        <>
            <div className="font-inspector">
                <div className="inspector-title text">{site.domain}</div>
                <div className="inspector-desc text">#{site.rank} - {site.category}</div>
                <div className="inspector-sub text">Fonts</div>
            </div>
            <div className="inspector-sites">
                {fonts.map((font, i) => (
                    font && <div className="search-row" key={i}>
                        <button 
                            className="text" 
                            key={font ?? i}
                            onClick={() => window.open(`https://${site.domain}`, '_blank')}
                        >
                            {font}
                        </button>
                        
                    </div>
                ))}
            </div>
        </>
    );
}

type TagSplit = "subset" | "style" | "classification";

export interface TagType {
    label: string,
    type: TagSplit
}

function FontInspector({row, tagCallback}: {row: FontRow, tagCallback: (data: TagType) => void}) {

    const [ pageIn, setPageIn ] = useState<number>(1);
    const [ siteParams, setSiteParams ] = useState<SiteFilter | null>({ font: row.font, page: 1 });

    useEffect(() => {
        setPageIn(1);
        setSiteParams({ font: row.font, page: 1 });
    }, [row.font]);

    const submit = (paging?: 'next' | 'back') => {
        const page = paging ? (paging === 'next' ? pageIn + 1 : pageIn - 1) : 1;
        setSiteParams({ font: row.font, page });
        setPageIn(page);
    };

    const {
        data: results,
        error,
        isError,
        isFetching,
        refetch,
    } = useSiteSearch(siteParams);
    
    console.log("data:", results);

    const splitStyles: (TagType[]) = row.style_tags ? row.style_tags.split(';').map(
        str => ({label: str, type: "style" as const})
    ) : [];
    const splitSubsets: (TagType[]) = row.subsets ? row.subsets.split(';').map(
        str => ({label: str, type: "subset" as const})
    ) : [];
    const combined: TagType[] = [
        ...[{ label: row.classification, type: "classification" as const }],
        ...splitStyles, 
        ...splitSubsets,
    ].sort((a, b) => (a.label.localeCompare(b.label)));

    return (
        <>
            <div className="font-inspector">
                <div className="inspector-title text">{row.font}</div>
                <div className="inspector-desc text">{row.notes}</div>
                <div className="tag-map">
                    {combined.map((tag, i) => {
                        return <div key={i}>
                            <button className={`
                                ${tag.type == 'style' ? 'button-rev' 
                                : tag.type == 'classification' ? 'button-not-rev'
                                : 'button-img-rev'
                                }
                            `}
                                onClick={() => tagCallback(tag)}
                            >
                                {tag.label}
                            </button>
                        </div>
                    })}
                </div>
                <div className="inspector-sub text">{row.hits} site{row.hits != 1 && 's'}</div>
            </div>
            <div className="inspector-sites">
                {isFetching && !results && !isError && (
                    <div className="text">loading…</div>
                )}
                {isError && (
                    <div>
                        <button type="button" className='text' style={{ pointerEvents: 'none' }}>
                            {error instanceof Error ? error.message : "Something went wrong."}
                        </button>
                        <button type="button" onClick={() => refetch()}>Retry</button>
                    </div>
                )}
                {results?.data.map((site, i) => (
                    <div className="search-row" key={i}>
                        <button 
                            className="text" 
                            key={site.domain ?? i}
                            onClick={() => window.open(`https://${site.domain}`, '_blank')}
                        >
                            {site.domain}
                        </button>
                        <button 
                            type="button" 
                            className='img-btn button-not' 
                            onClick={() => window.open(`https://${site.domain}`, '_blank')}
                        >
                            <img src='link.svg'/>
                        </button>
                    </div>
                ))}
            </div>

            <Pagination submit={submit} results={results} pageIn={pageIn} disabled={isFetching} />
        </>
    );
}

export default function DisplayNav({
    current,
    tagCallback,
    catCallback
}: {
    current: SiteRow | FontRow,
    tagCallback: (data: TagType) => void,
    catCallback: (category: string) => void
}) {

    const [ nowSelected, setNowSelected ] = useState<(SiteRow | FontRow)>(current);
    const [ history, setHistory ] = useState<(SiteRow | FontRow)[]>([current]);

    return (
        <div className="display-screen">
            {nowSelected._tag == "FontRow" ? 
                <FontInspector row={nowSelected} tagCallback={tagCallback}/>
            :
            <SiteInspector site={nowSelected} catCallback={catCallback}/>
            }
        </div>
    );
}